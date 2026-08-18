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
| 2. Crawl | `src/pipeline/crawler.py` | Crawls homepages with Crawl4AI, extracts RSS feeds, JSON-LD, language, sections, authors, robots.txt |
| 3. LLM Extract | `src/pipeline/crawler.py` | Re-crawls all successfully crawled candidates with Crawl4AI's LLM extraction (Ollama) to analyze page content, detect news sites, identify language/sections even when heuristics miss them |
| 4. Classify | `src/pipeline/classifier.py` | Sends heuristic + LLM signals to Ollama, labels each candidate `NEWS_SOURCE` / `DISCOVERY_SOURCE` / `REJECT` |
| 5. Score | `src/pipeline/scorer.py` | Scores non-rejected candidates 0–100 on weighted signals and assigns a polling tier |

The LLM extraction stage is critical for non-English sites where heuristic signals (RSS, URL patterns, lang attributes) are often absent.

Crawl4AI logs interleave with progress output because crawling runs concurrently — that's normal.

## Output

Each stage writes JSON to `output/<location_slug>/`:

```
output/north_macedonia_skopje/
  discovery.json
  crawl.json
  classification.json
  scoring.json
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
- `httpx` — async fetching of robots.txt
- `requests` — Ollama API calls

## Context

This pipeline is intended to replace the paid Newsdata.io dependency in the companion
**NewsAggregatorApp**: discovered sources (and their RSS feeds) become the article ingestion
layer, while `DISCOVERY_SOURCE` results can be crawled recursively to find more sources.

## Not Yet Implemented

- CLI arguments for city/country
- Batch mode for multiple locations
- RSS feed validation (confirming discovered feeds are live)
- Merging heuristic + LLM crawl into a single pass (currently crawls each site twice)
- Output format matching NewsAggregatorApp's Article schema