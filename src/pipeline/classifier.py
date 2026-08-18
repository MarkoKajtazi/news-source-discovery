import json

import requests

from src.config import CLASSIFICATION_SCHEMA, MODEL, OLLAMA_URL, SYSTEM_PROMPT
from src.models import Candidate, ClassificationResult, CrawlSignals


def _build_candidate_summary(candidate: Candidate) -> str:
    signals = candidate.signals or CrawlSignals()
    loc = signals.location
    loc_str = f'{{"name": "{loc.name}", "country": "{loc.country}"}}' if loc.name or loc.country else "unknown"
    parts = [
        f"Domain: {candidate.domain}",
        f"URL: {candidate.url}",
        f"Title: {candidate.title}",
        f"Description: {candidate.description}",
        f"Page title: {signals.page_title}",
        f"Meta description: {signals.meta_description}",
        f"Language: {signals.language}",
        f"RSS feeds: {len(signals.rss_feeds)}",
        f"JSON-LD types: {', '.join(signals.json_ld_types) or 'none'}",
        f"Internal links: {signals.internal_links_count}",
        f"Article-like paths: {signals.article_like_paths}",
        f"Has date patterns: {signals.has_date_patterns}",
        f"Sections: {', '.join(signals.sections[:15]) or 'none'}",
        f"Authors found: {len(signals.authors)}",
        f"Location: {loc_str}",
        f"Search occurrences: {candidate.search_occurrences}",
        f"Matched queries: {', '.join(candidate.queries[:5])}",
    ]
    if signals.content_snippet:
        parts.append(f"Content snippet: {signals.content_snippet[:300]}")
    if signals.llm_signals:
        llm = signals.llm_signals
        parts.append(f"LLM analysis - Is news site: {llm.is_news_site}")
        parts.append(f"LLM analysis - Has original articles: {llm.has_original_articles}")
        parts.append(f"LLM analysis - Content type: {llm.content_type}")
        parts.append(f"LLM analysis - Language: {llm.language}")
        parts.append(f"LLM analysis - Sections: {', '.join(llm.sections[:10]) or 'none'}")
        parts.append(f"LLM analysis - Has RSS: {llm.has_rss}")
        parts.append(f"LLM analysis - Description: {llm.site_description}")
    return "\n".join(parts)


def classify_candidate(candidate: Candidate) -> ClassificationResult:
    """Classify a single candidate using Ollama."""
    summary = _build_candidate_summary(candidate)

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": summary},
                ],
                "stream": False,
                "format": CLASSIFICATION_SCHEMA,
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        result = json.loads(content)

        return ClassificationResult(
            classification=result["classification"],
            confidence=float(result["confidence"]),
            reason=result["reason"],
        )
    except Exception as e:
        print(f"  [classify error] {candidate.domain}: {e}")
        return ClassificationResult(reason=f"Classification failed: {e}")


def classify_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Classify all candidates sequentially."""
    print(f"\nClassifying {len(candidates)} candidates with {MODEL}...\n")

    for i, candidate in enumerate(candidates):
        signals = candidate.signals or CrawlSignals()

        if not signals.crawl_success:
            candidate.classification = ClassificationResult(
                confidence=1.0,
                reason="Crawl failed",
            )
            print(f"  [{i + 1}/{len(candidates)}] {candidate.domain:<35} -> REJECT (crawl failed)")
            continue

        result = classify_candidate(candidate)
        candidate.classification = result
        print(f"  [{i + 1}/{len(candidates)}] {candidate.domain:<35} -> {result.classification} ({result.confidence:.2f})")

    news = sum(1 for c in candidates if c.classification and c.classification.classification == "NEWS_SOURCE")
    discovery = sum(1 for c in candidates if c.classification and c.classification.classification == "DISCOVERY_SOURCE")
    reject = sum(1 for c in candidates if c.classification and c.classification.classification == "REJECT")
    print(f"\n  Results: {news} news, {discovery} discovery, {reject} rejected\n")

    return candidates
