import asyncio
import json
import os
from dataclasses import asdict
from src.config import OUTPUT_DIR
from src.models import Candidate, TargetLocation
from src.pipeline.classifier import classify_candidates
from src.pipeline.crawler import crawl_and_extract
from src.pipeline.discover import discover
from src.pipeline.scorer import score_candidates


def _save_stage(
    location_dir: str,
    filename: str,
    candidates: list[Candidate],
    loc: TargetLocation,
):
    """Save stage output to a JSON file.

    The location is written into the document rather than left implicit in the
    directory name: `location.iso2` and `location.city_id` are the foreign keys
    an importer needs to insert these rows, and parsing them back out of a
    folder name would mean matching on country spellings.
    """
    os.makedirs(location_dir, exist_ok=True)
    path = os.path.join(location_dir, filename)
    data = {
        "location": asdict(loc),
        "candidates": [asdict(c) for c in candidates],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Saved {path} ({len(candidates)} candidates)")


def main():
    # Stands in for the request payload the .NET backend will post. `iso2` is
    # the identity; the names are search-query text only.
    location = TargetLocation(
        iso2="MK",
        iso3="MKD",
        country_name="North Macedonia",
        city="Skopje",
        city_local_name="Скопје",
    )

    location_dir = os.path.join(OUTPUT_DIR, location.slug)

    results = discover(location)
    _save_stage(location_dir, "1_discovery.json", results, location)

    # Crawl candidates for site signals, then run LLM extraction on the same browser
    enriched = asyncio.run(crawl_and_extract(results))
    _save_stage(location_dir, "2_crawl.json", enriched, location)

    # Classify candidates using Ollama
    classified = classify_candidates(enriched)
    _save_stage(location_dir, "3_classification.json", classified, location)

    # Score candidates by relevance
    scored = score_candidates(classified, location)
    _save_stage(location_dir, "4_scoring.json", scored, location)

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
