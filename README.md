# News Source Discovery

A pipeline that automatically discovers and classifies news sources for a given city/country.

It searches DuckDuckGo for candidate sites, filters out obvious non-news domains, crawls each
homepage with a headless browser to extract signals (RSS feeds, language, sections, article
paths, etc.), classifies each candidate with a local LLM, and scores the survivors by relevance.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Requires [Ollama](https://ollama.com) running locally with the `gpt-oss:120b-cloud` model available.

## Running

```bash
python main.py
```

## Pipeline

| Stage | Module | What it does |
|-------|--------|--------------|
| 1. Discover | `src/pipeline/discover.py` | Runs search queries (English + local-language terms), dedupes by domain, applies blocklist filters |
| 2. Crawl & extract | `src/pipeline/crawler.py` | Fetches each homepage **once** with Crawl4AI. The resulting markdown feeds both the BeautifulSoup heuristics (RSS feeds, JSON-LD, language, sections, authors, robots.txt) and an Ollama extraction call that reads the page content |
| 3. Classify | `src/pipeline/classifier.py` | Sends heuristic + LLM signals to Ollama, labels each candidate `NEWS_SOURCE` / `DISCOVERY_SOURCE` / `REJECT` |
| 4. Score | `src/pipeline/scorer.py` | Scores non-rejected candidates 0–100 on weighted signals and assigns a polling tier |

The LLM extraction is critical for non-English sites where heuristic signals (RSS, URL patterns, lang attributes) are often absent. It runs on the markdown already in hand — the page is never fetched twice. Pass `use_llm=False` to skip it, or `llm_only_weak=True` to run it only where the heuristics came back empty.

**Homepages, not search hits.** Search results are often deep pages (`/tag/skopje/`), which lack the `<head>` feed links and structured data the heuristics need. The crawler reduces each result to its homepage first and keeps the original URL for reference.

**RSS discovery is two-tier:** `<head>` link tags first, then well-known paths (`/feed`, `/rss`, `/rss.xml`, …) if none are found. Probed URLs are confirmed by content-type and body sniff, since some sites serve HTTP 200 HTML for `/rss` rather than a 404.

Crawl4AI logs interleave with progress output because crawling runs concurrently — that's normal.

## Output

Each stage writes JSON to `output/<location_slug>/`:

```
output/north_macedonia_skopje/
  1_discovery.json
  2_crawl.json
  3_classification.json
  4_scoring.json
```

## Project Structure

```
main.py                      # orchestrator (entry point)
src/
  config.py                  # all configuration: queries, filters, prompts, weights
  models.py                  # dataclasses: Candidate, CrawlSignals, ClassificationResult, ScoringResult
  pipeline/
    discover.py
    crawler.py
    classifier.py
    scorer.py
output/                      # pipeline JSON output (gitignored)
```

All tuning knobs — search query templates, rejected domains, the LLM prompt and schema, and the
scoring weights — live in `src/config.py`.

## Dependencies

- `ddgs` — DuckDuckGo search
- `crawl4ai` — headless browser crawling (needs Playwright Chromium)
- `beautifulsoup4` — HTML parsing for signal extraction
- `httpx` — async HTTP: robots.txt, RSS feed probing, Ollama extraction calls
- `requests` — Ollama API calls (classifier)

## Context

This pipeline is intended to replace the paid Newsdata.io dependency in the companion
**NewsAggregatorApp**: discovered sources (and their RSS feeds) become the article ingestion
layer, while `DISCOVERY_SOURCE` results can be crawled recursively to find more sources.

## Notes

Ollama's `format=<schema>` argument does **not** constrain `gpt-oss:120b-cloud` — given only a
schema it returns prose, and told to emit JSON it invents its own field names. Both prompts in
`src/config.py` therefore name every field explicitly in the prompt text. If you change a
schema, change the prompt to match.

## Not Yet Implemented

- FastAPI endpoints
- CLI arguments for city/country (currently hardcoded in `main.py`)
- Batch mode for multiple locations
- Validation of feeds found in `<head>` (only probed feeds are content-checked)
- Test suite
- Output format matching NewsAggregatorApp's Article schema