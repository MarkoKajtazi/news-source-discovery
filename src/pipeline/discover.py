import re
import time
from urllib.parse import urlparse

from ddgs import DDGS

from src.config import (
    COUNTRY_ONLY_TEMPLATES,
    LOCAL_NEWS_TERMS,
    QUERY_TEMPLATES,
    REJECTED_DOMAINS,
    REJECTED_PATTERNS,
)
from src.models import Candidate, TargetLocation


def generate_queries(loc: TargetLocation) -> list[str]:
    """Build a list of search queries for the given location.

    English templates use the country's display name; local-language templates
    prefer the city's local name, because a Macedonian outlet writes "Скопје",
    not "Skopje". Both spellings are searched — some sites do mix scripts.
    """
    templates = QUERY_TEMPLATES if loc.city else COUNTRY_ONLY_TEMPLATES
    queries = []

    for t in templates:
        try:
            q = t.format(city=loc.city or "", country=loc.country_name).strip()
            if q:
                queries.append(q)
        except KeyError:
            continue

    # Adding local-language queries. Keyed by ISO code, not by country name.
    local_terms = LOCAL_NEWS_TERMS.get(loc.iso2.upper(), [])
    city_forms = [c for c in (loc.city_local_name, loc.city) if c]
    for term in local_terms:
        for city_form in city_forms:
            queries.append(f"{city_form} {term}")
        queries.append(f"{loc.country_name} {term}")

    # city_local_name may equal city, and templates can collide — dedupe while
    # preserving order, since each query costs a rate-limited round trip.
    return list(dict.fromkeys(queries))


def search_ddg(query: str, max_results: int = 20) -> list[dict]:
    """Run a single DDG search and return results."""
    try:
        return DDGS().text(query, max_results=max_results)
    except Exception as e:
        print(f"  [warn] search failed for '{query}': {e}")
        return []


def collect_candidates(
    queries: list[str],
    max_results_per_query: int = 20,
    delay: float = 1.0,
) -> list[dict]:
    """Run all queries and collect raw results."""
    all_results = []
    for i, q in enumerate(queries):
        print(f"  [{i + 1}/{len(queries)}] Searching: {q}")
        results = search_ddg(q, max_results=max_results_per_query)
        for result in results:
            result["_query"] = q
        all_results.extend(results)
        if i < len(queries) - 1:
            time.sleep(delay)
    return all_results


def extract_domain(url: str) -> str:
    """Extract the root domain from a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    return domain


def extract_homepage(url: str) -> str:
    """Reduce a search-result URL to the site's homepage.

    Search hits are often deep pages (e.g. /where/north-macedonia), which lack
    the <head> feed links and structured data the crawler looks for.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}/"


def deduplicate(results: list[dict]) -> dict[str, Candidate]:
    """Deduplicate by domain while preserving discovery evidence."""
    seen: dict[str, Candidate] = {}
    for r in results:
        url = r.get("href") or r.get("url", "")
        if not url:
            continue
        domain = extract_domain(url)
        if not domain:
            continue
        query = r.get("_query", "")
        if domain not in seen:
            seen[domain] = Candidate(
                domain=domain,
                url=url,
                homepage_url=extract_homepage(url),
                title=r.get("title", ""),
                description=r.get("body", ""),
            )
        seen[domain].search_occurrences += 1
        if query and query not in seen[domain].queries:
            seen[domain].queries.append(query)
    return seen


def is_rejected(domain: str) -> bool:
    """Check if a domain should be filtered out."""
    if domain in REJECTED_DOMAINS:
        return True
    for parent in REJECTED_DOMAINS:
        if domain.endswith("." + parent):
            return True
    for pattern in REJECTED_PATTERNS:
        if re.search(pattern, domain):
            return True
    return False


def apply_hard_filters(candidates: dict[str, Candidate]) -> dict[str, Candidate]:
    """Remove domains that are clearly not news sources."""
    filtered = {}
    rejected_count = 0
    for domain, info in candidates.items():
        if is_rejected(domain):
            rejected_count += 1
        else:
            filtered[domain] = info
    print(f"  Hard filters: rejected {rejected_count}, kept {len(filtered)}")
    return filtered


def discover(loc: TargetLocation) -> list[Candidate]:
    """Run the full discovery pipeline."""
    where = f"{loc.city}, {loc.country_name}" if loc.city else loc.country_name
    print(f"\nDiscovering news sources for: {where} [{loc.iso2}]\n")

    queries = generate_queries(loc)
    print(f"Generated {len(queries)} search queries\n")

    print("Searching...")
    raw_results = collect_candidates(queries)
    print(f"\n  Collected {len(raw_results)} raw results\n")

    candidates = deduplicate(raw_results)
    print(f"  Unique domains: {len(candidates)}")

    candidates = apply_hard_filters(candidates)

    results = sorted(candidates.values(), key=lambda x: x.domain)

    print(f"\n  Final candidates: {len(results)}\n")
    return results
