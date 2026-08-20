"""Feed discovery and validation.

Not a pipeline stage. Feed data is *input* to classification and scoring —
`classifier.py` puts feeds in the LLM prompt and `scorer.py` weights them — so
validation has to finish before those stages run, and it lives inside the crawl
stage rather than after it.

It is a module rather than stage code because the production side needs to
re-run exactly this logic on a schedule to maintain a source's "is the feed
still alive" flag. Both callers share `validate_feeds()`.

The crawler only *nominates* URLs (from `<head>` links); nothing here trusts a
URL until it has been fetched and parsed.
"""

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import httpx

from src.config import (
    FEED_FETCH_TIMEOUT,
    FEED_MAX_BYTES,
    FEED_MAX_PER_CANDIDATE,
    FEED_MIN_ENTRIES,
    FEED_PATHS,
    FEED_URL_BLOCKLIST,
)
from src.models import FeedInfo


def is_useful_feed(url: str) -> bool:
    """Reject feed URLs that are known to carry no articles."""
    return not any(blocked in url.lower() for blocked in FEED_URL_BLOCKLIST)


def _host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _is_internal(link: str, domain: str) -> bool:
    """True if `link` belongs to `domain` or one of its subdomains."""
    host = _host_of(link)
    if not host:
        # Relative link — only a site's own feed emits these.
        return True
    return host == domain or host.endswith("." + domain)


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                # feedparser normalises struct_time to UTC.
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _entry_origin(entry) -> str:
    """The outlet an entry actually came from.

    `link` alone is not enough: aggregators wrap entries in their own redirect
    URLs (news.google.com/rss/articles/...), which makes every entry look
    internal. RSS `<source url>` / Atom `<source>` names the real originating
    outlet, and only aggregators emit it — publishers leave it empty.
    """
    source = entry.get("source")
    if isinstance(source, dict):
        origin = source.get("href") or source.get("link")
        if origin:
            return origin
    return entry.get("link") or ""


def _entry_body_length(entry) -> int:
    longest = 0
    for block in entry.get("content") or []:
        longest = max(longest, len(block.get("value") or ""))
    return max(longest, len(entry.get("summary") or ""))


def _parse_feed(raw: bytes, url: str, domain: str) -> FeedInfo:
    """Turn raw feed bytes into a FeedInfo. Pure CPU, no network."""
    info = FeedInfo(url=url)
    try:
        parsed = feedparser.parse(raw)
    except Exception:
        info.status = "unparseable"
        return info

    entries = parsed.entries or []

    # `version` is "" for anything feedparser could not identify as a feed —
    # a far stronger check than sniffing the first bytes for "<rss".
    if not parsed.get("version") and not entries:
        info.status = "not_feed" if not parsed.get("bozo") else "unparseable"
        return info

    info.title = (parsed.feed.get("title") or "")[:200]
    info.language = (parsed.feed.get("language") or "").strip()
    info.entry_count = len(entries)

    if len(entries) < FEED_MIN_ENTRIES:
        info.status = "empty"
        return info

    dates = [d for d in (_entry_datetime(e) for e in entries) if d]
    if dates:
        info.latest_entry = max(dates).isoformat()

    # A feed carrying article bodies is worth more to ingestion than one
    # carrying only headlines.
    info.has_full_content = any(_entry_body_length(e) > 500 for e in entries)

    origins = [o for o in (_entry_origin(e) for e in entries) if o]
    if origins:
        external = sum(1 for origin in origins if not _is_internal(origin, domain))
        info.external_link_ratio = round(external / len(origins), 3)
        info.distinct_sources = len({_host_of(o) for o in origins if _host_of(o)})

    info.valid = True
    info.status = "ok"
    return info


async def validate_feed(client: httpx.AsyncClient, url: str, domain: str) -> FeedInfo:
    """Fetch one candidate feed URL and report what it really is."""
    try:
        resp = await client.get(url, timeout=FEED_FETCH_TIMEOUT)
    except httpx.TimeoutException:
        return FeedInfo(url=url, status="timeout")
    except Exception:
        return FeedInfo(url=url, status="error")

    if resp.status_code != 200:
        return FeedInfo(url=url, status=f"http_{resp.status_code}")

    raw = resp.content[:FEED_MAX_BYTES]
    # feedparser is synchronous and can be slow on large documents.
    info = await asyncio.to_thread(_parse_feed, raw, str(resp.url), domain)
    if not info.valid:
        # Report what was actually probed. A site that redirects /feed to its
        # homepage would otherwise be recorded as a failed attempt on a URL
        # nobody tried ("https://rashtranews.com/ -> unparseable"), and the
        # non-200 branch above already records the requested URL — the two
        # must agree or the failure list is misleading.
        info.url = url
    # Valid feeds keep the post-redirect URL: that is the canonical location to
    # poll (e.g. /rss -> /uk/rss on theguardian.com).
    return info


def _identity(info: FeedInfo) -> tuple:
    """Key for collapsing URLs that serve the same feed.

    /feed and /feed/ are one resource on most CMSes, and many sites expose the
    same document at several paths.
    """
    if info.valid:
        return ("feed", info.title, info.entry_count)
    return ("url", info.url.rstrip("/"))


def _dedupe(infos: list[FeedInfo]) -> list[FeedInfo]:
    seen = set()
    unique = []
    for info in infos:
        key = _identity(info)
        if key in seen:
            continue
        seen.add(key)
        unique.append(info)
    return unique


async def validate_feeds(
    client: httpx.AsyncClient, urls: list[str], domain: str
) -> list[FeedInfo]:
    """Validate a set of candidate feed URLs concurrently."""
    wanted = []
    seen = set()
    for url in urls:
        key = url.rstrip("/")
        if key in seen or not is_useful_feed(url):
            continue
        seen.add(key)
        wanted.append(url)

    if not wanted:
        return []

    results = await asyncio.gather(
        *(validate_feed(client, url, domain) for url in wanted),
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, FeedInfo)]


async def discover_feeds(
    client: httpx.AsyncClient, domain: str, nominated: list[str]
) -> list[FeedInfo]:
    """Resolve a domain's feeds, validating every URL before trusting it.

    Tries the URLs the homepage `<head>` nominated first, and only falls back to
    probing FEED_PATHS if none of them turn out to be real feeds. Unlike the
    previous split, `<head>` links get the same scrutiny as probed paths.
    """
    infos = await validate_feeds(client, nominated, domain)
    valid = [f for f in infos if f.valid]

    if not valid:
        probed = await validate_feeds(
            client, [f"https://{domain}{path}" for path in FEED_PATHS], domain
        )
        infos.extend(probed)
        valid = [f for f in infos if f.valid]

    if valid:
        # Richest feed first — most entries, then freshest.
        valid = _dedupe(sorted(valid, key=lambda f: (f.entry_count, f.latest_entry), reverse=True))
        return valid[:FEED_MAX_PER_CANDIDATE]

    # Keep the failures so the JSON output shows what was tried and why it lost.
    return _dedupe(infos)[:FEED_MAX_PER_CANDIDATE]


async def revalidate_feeds(urls: list[str], domain: str) -> list[FeedInfo]:
    """Standalone entry point for a periodic liveness check.

    The discovery pipeline calls `discover_feeds` with its pooled client; a
    scheduled job that only wants to know whether stored feeds still work calls
    this instead. Same validation either way.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await validate_feeds(client, urls, domain)
