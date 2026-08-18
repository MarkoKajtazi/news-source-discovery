import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, LLMConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy

from src.config import (
    LLM_EXTRACTION_INSTRUCTION,
    LLM_EXTRACTION_SCHEMA,
    OLLAMA_BASE_URL,
    OLLAMA_PROVIDER,
)
from src.models import Candidate, CrawlSignals, LLMSignals, Location, RobotsTxt


def _extract_rss_feeds(soup: BeautifulSoup, base_url: str) -> list[str]:
    feeds = []
    for link in soup.find_all("link", type=re.compile(r"application/(rss|atom)\+xml", re.I)):
        href = link.get("href")
        if href:
            feeds.append(urljoin(base_url, href))
    return feeds


def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    entries = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                entries.extend(data)
            else:
                entries.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return entries


def _extract_language(soup: BeautifulSoup) -> str:
    html_tag = soup.find("html")
    if html_tag:
        lang = html_tag.get("lang") or html_tag.get("xml:lang") or ""
        return lang.strip()
    meta = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
    if meta:
        return (meta.get("content") or "").strip()
    return ""


def _extract_meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
    if not tag:
        tag = soup.find("meta", attrs={"property": re.compile(f"^{name}$", re.I)})
    return (tag.get("content", "") if tag else "").strip()[:300]


def _extract_internal_links(soup: BeautifulSoup, base_url: str, domain: str) -> list[str]:
    paths = []
    for a in soup.find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        parsed = urlparse(full)
        link_domain = parsed.netloc.lower().removeprefix("www.")
        if link_domain == domain:
            paths.append(parsed.path)
    return paths


def _count_article_paths(paths: list[str]) -> int:
    article_patterns = [
        r"/\d{4}/\d{2}/",
        r"/news/",
        r"/article/",
        r"/story/",
        r"/post/",
        r"/breaking/",
        r"/opinion/",
        r"/editorial/",
    ]
    return sum(
        1 for p in paths
        if any(re.search(pat, p, re.I) for pat in article_patterns)
    )


def _extract_sections(soup: BeautifulSoup, internal_paths: list[str]) -> list[str]:
    """Extract navigation sections (e.g. Politics, Sports, World)."""
    sections = set()
    for nav in soup.find_all("nav"):
        for a in nav.find_all("a", href=True):
            text = a.get_text(strip=True)
            if text and 2 <= len(text) <= 40:
                sections.add(text)
    if not sections:
        top_paths = set()
        for p in internal_paths:
            parts = [s for s in p.strip("/").split("/") if s]
            if parts:
                top_paths.add(parts[0])
        sections = {s.replace("-", " ").title() for s in top_paths if len(s) > 1 and not re.match(r"^\d+$", s)}
    return sorted(sections)[:30]


def _has_date_patterns(html: str) -> bool:
    patterns = [
        r"\d{4}-\d{2}-\d{2}",
        r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}",
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    ]
    return any(re.search(p, html) for p in patterns)


def _extract_authors(soup: BeautifulSoup, json_ld: list[dict]) -> list[str]:
    authors = set()
    # From JSON-LD
    for entry in json_ld:
        author = entry.get("author")
        if isinstance(author, dict):
            name = author.get("name", "")
            if name:
                authors.add(name)
        elif isinstance(author, list):
            for a in author:
                name = a.get("name", "") if isinstance(a, dict) else str(a)
                if name:
                    authors.add(name)
    # From meta tags
    for attr in ["author", "article:author"]:
        val = _extract_meta(soup, attr)
        if val:
            authors.add(val)
    # From common author markup
    for selector in [
        {"class_": re.compile(r"author", re.I)},
        {"rel": "author"},
        {"itemprop": "author"},
    ]:
        for tag in soup.find_all(["a", "span", "div", "p"], **selector):
            text = tag.get_text(strip=True)
            if text and 3 <= len(text) <= 80:
                authors.add(text)
    return sorted(authors)[:20]


def _extract_location(soup: BeautifulSoup, json_ld: list[dict]) -> Location:
    """Try to extract geographic location from structured data."""
    for entry in json_ld:
        for f in ["location", "contentLocation", "address"]:
            loc = entry.get(f)
            if isinstance(loc, dict):
                name = loc.get("name") or loc.get("addressLocality") or ""
                country = loc.get("addressCountry") or ""
                if name or country:
                    return Location(name=name, country=country)
    name = _extract_meta(soup, "geo.placename")
    country = _extract_meta(soup, "geo.country")
    return Location(name=name, country=country)


async def _fetch_robots_txt(domain: str, timeout: float = 10.0) -> RobotsTxt:
    """Fetch and parse robots.txt."""
    url = f"https://{domain}/robots.txt"
    result = RobotsTxt()
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=timeout)
            if resp.status_code != 200:
                result.raw = f"HTTP {resp.status_code}"
                return result
            text = resp.text
            result.raw = text[:2000]

            current_agent_applies = False
            for line in text.splitlines():
                line = line.strip()
                if line.lower().startswith("user-agent:"):
                    agent = line.split(":", 1)[1].strip().lower()
                    current_agent_applies = agent == "*"
                elif current_agent_applies:
                    if line.lower().startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path:
                            result.disallowed_paths.append(path)
                    elif line.lower().startswith("allow:"):
                        path = line.split(":", 1)[1].strip()
                        if path:
                            result.allowed_paths.append(path)
                if line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    if sitemap_url:
                        result.sitemaps.append(sitemap_url)
    except Exception:
        result.raw = "fetch failed"
    return result


def _extract_json_ld_types(json_ld: list[dict]) -> list[str]:
    types = set()
    for entry in json_ld:
        t = entry.get("@type")
        if isinstance(t, str):
            types.add(t)
        elif isinstance(t, list):
            types.update(t)
    return sorted(types)


async def crawl_candidate(crawler: AsyncWebCrawler, candidate: Candidate) -> Candidate:
    """Crawl a candidate's homepage and extract site signals."""
    signals = CrawlSignals()

    # Fetch robots.txt
    signals.robots_txt = await _fetch_robots_txt(candidate.domain)

    try:
        config = CrawlerRunConfig(
            word_count_threshold=10,
            page_timeout=20000,
            wait_until="domcontentloaded",
        )
        result = await crawler.arun(url=candidate.url, config=config)

        if not result.success:
            print(f"  [fail] {candidate.domain}: {result.error_message}")
            candidate.signals = signals
            return candidate

        html = result.html
        signals.crawl_success = True

        soup = BeautifulSoup(html, "lxml")

        # Basic metadata
        title_tag = soup.find("title")
        signals.page_title = title_tag.get_text(strip=True)[:200] if title_tag else ""
        signals.meta_description = _extract_meta(soup, "description")
        signals.language = _extract_language(soup)

        # RSS feeds
        signals.rss_feeds = _extract_rss_feeds(soup, candidate.url)

        # JSON-LD
        json_ld = _extract_json_ld(soup)
        signals.json_ld_types = _extract_json_ld_types(json_ld)

        # Internal links and article paths
        internal_paths = _extract_internal_links(soup, candidate.url, candidate.domain)
        signals.internal_links_count = len(internal_paths)
        signals.article_like_paths = _count_article_paths(internal_paths)

        # Sections
        signals.sections = _extract_sections(soup, internal_paths)

        # Dates
        signals.has_date_patterns = _has_date_patterns(html)

        # Authors
        signals.authors = _extract_authors(soup, json_ld)

        # Location
        signals.location = _extract_location(soup, json_ld)

        # Content snippet from Crawl4AI's extracted markdown
        if result.markdown:
            text = result.markdown.raw_markdown if hasattr(result.markdown, "raw_markdown") else str(result.markdown)
            signals.content_snippet = text[:500]

    except Exception as e:
        print(f"  [error] {candidate.domain}: {e}")

    candidate.signals = signals
    return candidate


async def crawl_candidates(candidates: list[Candidate], max_concurrent: int = 5) -> list[Candidate]:
    """Crawl all candidates and enrich them with signals."""
    print(f"\nCrawling {len(candidates)} candidates (max {max_concurrent} concurrent)...\n")

    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_crawl(crawler, candidate, index):
        async with semaphore:
            print(f"  [{index + 1}/{len(candidates)}] Crawling: {candidate.domain}")
            return await crawl_candidate(crawler, candidate)

    browser_config = BrowserConfig(headless=True, verbose=False)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        tasks = [limited_crawl(crawler, c, i) for i, c in enumerate(candidates)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  [error] {candidates[i].domain}: {r}")
            candidates[i].signals = CrawlSignals()
            enriched.append(candidates[i])
        else:
            enriched.append(r)

    success = sum(1 for c in enriched if c.signals and c.signals.crawl_success)
    print(f"\n  Crawl complete: {success}/{len(enriched)} successful\n")
    return enriched


def _has_weak_signals(signals: CrawlSignals) -> bool:
    """Check if heuristic extraction produced weak signals."""
    return (
        signals.crawl_success
        and signals.article_like_paths == 0
        and not signals.rss_feeds
        and not signals.language
    )


def _parse_llm_result(raw: str) -> LLMSignals:
    """Parse LLM extraction result into LLMSignals."""
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            data = data[0]
        return LLMSignals(
            is_news_site=bool(data.get("is_news_site", False)),
            has_original_articles=bool(data.get("has_original_articles", False)),
            language=str(data.get("language", "")),
            content_type=str(data.get("content_type", "")),
            sections=list(data.get("sections", [])),
            has_rss=bool(data.get("has_rss", False)),
            site_description=str(data.get("site_description", "")),
        )
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        print(f"    [llm parse error] {e}")
        return LLMSignals()


async def llm_crawl_candidate(crawler: AsyncWebCrawler, candidate: Candidate) -> Candidate:
    """Re-crawl a candidate with LLM extraction to enhance weak signals."""
    llm_config = LLMConfig(
        provider=OLLAMA_PROVIDER,
        api_token="no-token",
        base_url=OLLAMA_BASE_URL,
    )
    strategy = LLMExtractionStrategy(
        llm_config=llm_config,
        instruction=LLM_EXTRACTION_INSTRUCTION,
        schema=LLM_EXTRACTION_SCHEMA,
        extraction_type="schema",
        apply_chunking=False,
        verbose=False,
    )
    config = CrawlerRunConfig(
        word_count_threshold=10,
        page_timeout=30000,
        wait_until="domcontentloaded",
        extraction_strategy=strategy,
    )

    try:
        result = await crawler.arun(url=candidate.url, config=config)
        if result.success and result.extracted_content:
            llm_signals = _parse_llm_result(result.extracted_content)
            candidate.signals.llm_signals = llm_signals

            # Fill in gaps from heuristic extraction
            if not candidate.signals.language and llm_signals.language:
                candidate.signals.language = llm_signals.language
            if not candidate.signals.sections and llm_signals.sections:
                candidate.signals.sections = llm_signals.sections
        else:
            print(f"    [llm fail] {candidate.domain}: {getattr(result, 'error_message', 'no content')}")
    except Exception as e:
        print(f"    [llm error] {candidate.domain}: {e}")

    return candidate


async def llm_crawl_candidates(
    candidates: list[Candidate], max_concurrent: int = 3
) -> list[Candidate]:
    """Run LLM extraction on all successfully crawled candidates."""
    targets = [c for c in candidates if c.signals and c.signals.crawl_success]

    if not targets:
        print("\n  No successfully crawled candidates — skipping LLM extraction\n")
        return candidates

    print(f"\nLLM extraction for {len(targets)} candidates (max {max_concurrent} concurrent)...\n")

    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_llm_crawl(crawler, candidate, index):
        async with semaphore:
            print(f"  [{index + 1}/{len(targets)}] LLM extracting: {candidate.domain}")
            return await llm_crawl_candidate(crawler, candidate)

    browser_config = BrowserConfig(headless=True, verbose=False)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        tasks = [limited_llm_crawl(crawler, c, i) for i, c in enumerate(targets)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    enhanced = 0
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  [error] {targets[i].domain}: {r}")
        elif r.signals and r.signals.llm_signals:
            enhanced += 1

    print(f"\n  LLM extraction complete: {enhanced}/{len(targets)} enhanced\n")
    return candidates
