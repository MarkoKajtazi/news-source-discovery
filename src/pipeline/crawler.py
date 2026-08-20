import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from src.config import (
    LLM_EXTRACTION_INSTRUCTION,
    LLM_EXTRACTION_MAX_CHARS,
    LLM_EXTRACTION_SCHEMA,
    MODEL,
    OLLAMA_URL,
)
from src.models import Candidate, CrawlSignals, LLMSignals, Location, RobotsTxt
from src.pipeline.feeds import discover_feeds, is_useful_feed


def _nominate_head_feeds(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Collect feed URLs advertised in <head>.

    Nomination only — these are unverified URLs. `feeds.discover_feeds` decides
    whether any of them is really a feed.
    """
    nominated = []
    for link in soup.find_all("link", type=re.compile(r"application/(rss|atom)\+xml", re.I)):
        href = link.get("href")
        if href:
            full = urljoin(base_url, href)
            if is_useful_feed(full):
                nominated.append(full)
    return nominated


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


async def _fetch_robots_txt(
    client: httpx.AsyncClient, domain: str, timeout: float = 10.0
) -> RobotsTxt:
    """Fetch and parse robots.txt."""
    url = f"https://{domain}/robots.txt"
    result = RobotsTxt()
    try:
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


async def crawl_candidate(
    crawler: AsyncWebCrawler, client: httpx.AsyncClient, candidate: Candidate
) -> tuple[Candidate, str, list[str]]:
    """Crawl a candidate's homepage and extract site signals.

    Returns the candidate, the page markdown, and the feed URLs nominated by
    `<head>`. The markdown is handed to the LLM extraction step so the page is
    only ever fetched once; the nominated URLs go to feed validation, which
    runs outside the browser semaphore since it is plain HTTP.
    """
    signals = CrawlSignals()
    markdown = ""
    nominated_feeds: list[str] = []

    # The search hit is often a deep page; feed links and structured data
    # live on the homepage.
    page_url = candidate.homepage_url or candidate.url

    # Fetch robots.txt
    signals.robots_txt = await _fetch_robots_txt(client, candidate.domain)

    try:
        config = CrawlerRunConfig(
            word_count_threshold=10,
            page_timeout=20000,
            wait_until="domcontentloaded",
        )
        result = await crawler.arun(url=page_url, config=config)

        if not result.success:
            print(f"  [fail] {candidate.domain}: {result.error_message}")
            candidate.signals = signals
            return candidate, markdown, nominated_feeds

        html = result.html
        signals.crawl_success = True

        soup = BeautifulSoup(html, "lxml")

        # Basic metadata
        title_tag = soup.find("title")
        signals.page_title = title_tag.get_text(strip=True)[:200] if title_tag else ""
        signals.meta_description = _extract_meta(soup, "description")
        signals.language = _extract_language(soup)

        # Feed URLs advertised in <head>; validated later, outside this slot
        nominated_feeds = _nominate_head_feeds(soup, page_url)

        # JSON-LD
        json_ld = _extract_json_ld(soup)
        signals.json_ld_types = _extract_json_ld_types(json_ld)

        # Internal links and article paths
        internal_paths = _extract_internal_links(soup, page_url, candidate.domain)
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
            markdown = result.markdown.raw_markdown if hasattr(result.markdown, "raw_markdown") else str(result.markdown)
            signals.content_snippet = markdown[:500]

    except Exception as e:
        print(f"  [error] {candidate.domain}: {e}")

    candidate.signals = signals
    return candidate, markdown, nominated_feeds


def _has_weak_signals(signals: CrawlSignals, nominated_feeds: list[str]) -> bool:
    """Check if heuristic extraction produced weak signals.

    Uses the *nominated* feed URLs rather than validated ones on purpose: this
    decides whether to spend an LLM call, and it runs concurrently with feed
    validation, so reading `signals.feeds` here would be a race. Nominated
    `<head>` links are also the better measure — they are a property of the
    page the heuristics just read, whereas path probing is a network guess.
    """
    return (
        signals.crawl_success
        and signals.article_like_paths == 0
        and not nominated_feeds
        and not signals.language
    )


def _parse_llm_result(raw: str, domain: str = "") -> LLMSignals:
    """Parse LLM extraction result into LLMSignals."""
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            data = data[0]
        # The model sometimes invents its own field names; without this the
        # .get() defaults below would quietly produce an empty LLMSignals.
        if not any(k in data for k in LLM_EXTRACTION_SCHEMA["properties"]):
            print(f"    [llm schema mismatch] {domain}: got keys {sorted(data)[:6]}")
        return LLMSignals(
            is_news_site=bool(data.get("is_news_site", False)),
            has_original_articles=bool(data.get("has_original_articles", False)),
            language=str(data.get("language", "")),
            content_type=str(data.get("content_type", "")),
            sections=list(data.get("sections", [])),
            site_description=str(data.get("site_description", "")),
        )
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        print(f"    [llm parse error] {e}")
        return LLMSignals()


async def extract_signals_llm(
    client: httpx.AsyncClient, candidate: Candidate, markdown: str
) -> Candidate:
    """Extract signals from already-fetched markdown. Does not fetch the page."""
    try:
        resp = await client.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": LLM_EXTRACTION_INSTRUCTION},
                    {"role": "user", "content": markdown[:LLM_EXTRACTION_MAX_CHARS]},
                ],
                "stream": False,
                "format": LLM_EXTRACTION_SCHEMA,
            },
            timeout=180.0,
        )
        resp.raise_for_status()
        llm_signals = _parse_llm_result(resp.json()["message"]["content"], candidate.domain)
        candidate.signals.llm_signals = llm_signals

        # Fill in gaps from heuristic extraction
        if not candidate.signals.language and llm_signals.language:
            candidate.signals.language = llm_signals.language
        if not candidate.signals.sections and llm_signals.sections:
            candidate.signals.sections = llm_signals.sections
    except Exception as e:
        print(f"    [llm error] {candidate.domain}: {e}")

    return candidate


async def crawl_and_extract(
    candidates: list[Candidate],
    max_concurrent: int = 5,
    max_llm_concurrent: int = 3,
    max_feed_concurrent: int = 5,
    use_llm: bool = True,
    llm_only_weak: bool = False,
) -> list[Candidate]:
    """Crawl every candidate once, extracting heuristic, feed and LLM signals.

    Each page is fetched exactly once; the resulting markdown feeds both the
    BeautifulSoup heuristics and the Ollama extraction. The page slot is
    released before the LLM and feed slots are taken, so neither a slow model
    nor a slow feed host holds browser slots idle, and a candidate's follow-up
    work starts as soon as its own page is done rather than after the whole
    crawl finishes.

    Feed validation and LLM extraction run concurrently — they contend on
    different resources (arbitrary web hosts vs. Ollama) and write disjoint
    fields of `CrawlSignals`.
    """
    print(f"\nCrawling {len(candidates)} candidates (max {max_concurrent} concurrent)...")
    if use_llm:
        scope = "weak-signal candidates" if llm_only_weak else "all candidates"
        print(f"LLM extraction: {scope} (max {max_llm_concurrent} concurrent)")
    else:
        print("LLM extraction: disabled")
    print(f"Feed validation: max {max_feed_concurrent} concurrent\n")

    page_sem = asyncio.Semaphore(max_concurrent)
    llm_sem = asyncio.Semaphore(max_llm_concurrent)
    feed_sem = asyncio.Semaphore(max_feed_concurrent)
    llm_done = 0
    feeds_found = 0

    async def process(crawler, client, candidate, index):
        nonlocal llm_done, feeds_found
        async with page_sem:
            print(f"  [{index + 1}/{len(candidates)}] Crawling: {candidate.domain}")
            candidate, markdown, nominated = await crawl_candidate(crawler, client, candidate)

        if not candidate.signals.crawl_success:
            return candidate

        async def validate():
            nonlocal feeds_found
            async with feed_sem:
                candidate.signals.feeds = await discover_feeds(
                    client, candidate.domain, nominated
                )
            valid = candidate.signals.rss_feeds
            if valid:
                feeds_found += 1
                print(f"    Feeds validated: {candidate.domain} -> {len(valid)} live")

        async def extract():
            nonlocal llm_done
            if not (use_llm and markdown):
                return
            if llm_only_weak and not _has_weak_signals(candidate.signals, nominated):
                return
            async with llm_sem:
                print(f"    LLM extracting: {candidate.domain}")
                await extract_signals_llm(client, candidate, markdown)
                if candidate.signals.llm_signals:
                    llm_done += 1

        await asyncio.gather(validate(), extract())
        return candidate

    browser_config = BrowserConfig(headless=True, verbose=False)
    async with (
        AsyncWebCrawler(config=browser_config) as crawler,
        httpx.AsyncClient(follow_redirects=True) as client,
    ):
        tasks = [process(crawler, client, c, i) for i, c in enumerate(candidates)]
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
    print(f"\n  Crawl complete: {success}/{len(enriched)} successful")
    if use_llm:
        print(f"  LLM extraction: {llm_done} enhanced")
    print(f"  Feed validation: {feeds_found} candidates with at least one live feed")
    print()
    return enriched
