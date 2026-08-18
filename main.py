import asyncio
import json
import os
import re
from dataclasses import asdict
from src.config import OUTPUT_DIR
from src.models import Candidate
from src.pipeline.classifier import classify_candidates
from src.pipeline.crawler import crawl_candidates, llm_crawl_candidates
from src.pipeline.discover import discover
from src.pipeline.scorer import score_candidates


def _make_location_slug(city: str | None, country: str) -> str:
    """Create a filesystem-safe directory name from city/country."""
    parts = [country]
    if city:
        parts.append(city)
    slug = "_".join(parts).lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = slug.strip("_")
    return slug


def _save_stage(location_dir: str, filename: str, candidates: list[Candidate]):
    """Save stage output to a JSON file."""
    os.makedirs(location_dir, exist_ok=True)
    path = os.path.join(location_dir, filename)
    data = [asdict(c) for c in candidates]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Saved {path} ({len(candidates)} candidates)")


def main():
    city = "Skopje"
    country = "North Macedonia"

    location_dir = os.path.join(OUTPUT_DIR, _make_location_slug(city, country))

    results = discover(city, country)
    _save_stage(location_dir, "1_discovery.json", results)

    # Crawl candidates to extract site signals
    enriched = asyncio.run(crawl_candidates(results))

    # LLM extraction for candidates with weak heuristic signals
    enriched = asyncio.run(llm_crawl_candidates(enriched))
    _save_stage(location_dir, "2_crawl.json", enriched)

    # Classify candidates using Ollama
    classified = classify_candidates(enriched)
    _save_stage(location_dir, "3_classification.json", classified)

    # Score candidates by relevance
    scored = score_candidates(classified, city, country)
    _save_stage(location_dir, "4_scoring.json", scored)

    # Print final results grouped by classification
    for label in ("NEWS_SOURCE", "DISCOVERY_SOURCE", "REJECT"):
        group = [c for c in scored if c.classification and c.classification.classification == label]
        if not group:
            continue
        print(f"\n{'=' * 60}")
        print(f"  {label} ({len(group)})")
        print(f"{'=' * 60}")
        for r in group:
            cl = r.classification
            signals = r.signals
            sc = r.scoring
            rss = len(signals.rss_feeds) if signals else 0
            articles = signals.article_like_paths if signals else 0
            lang = (signals.language if signals else "") or "-"
            score_str = f"score={sc.score:5.1f} [{sc.polling_tier}]" if sc else ""
            print(
                f"  {r.domain:<35} conf={cl.confidence:.2f}  "
                f"rss={rss}  articles={articles}  lang={lang}  {score_str}"
            )
            print(f"    {cl.reason}")


if __name__ == "__main__":
    main()
