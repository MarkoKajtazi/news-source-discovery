from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RobotsTxt:
    raw: str = ""
    disallowed_paths: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)


@dataclass
class Location:
    name: str = ""
    country: str = ""


@dataclass
class LLMSignals:
    is_news_site: bool = False
    has_original_articles: bool = False
    language: str = ""
    content_type: str = ""
    sections: list[str] = field(default_factory=list)
    site_description: str = ""


@dataclass
class FeedInfo:
    """A candidate feed URL and what fetching it actually proved.

    `valid` means the URL parsed as a feed and carried at least
    FEED_MIN_ENTRIES entries — not merely that it returned HTTP 200.
    """

    url: str = ""
    valid: bool = False
    # ok | http_<code> | not_feed | unparseable | empty | timeout | error
    status: str = ""
    title: str = ""
    entry_count: int = 0
    latest_entry: str = ""  # ISO 8601 UTC, "" when no entry carried a date
    has_full_content: bool = False  # article bodies, not just headlines
    language: str = ""
    # Fraction of entries originating off the site's own domain, and how many
    # distinct outlets they came from. A publisher feed is ~0% / 1 outlet; an
    # aggregator republishing others is high / many.
    external_link_ratio: float = 0.0
    distinct_sources: int = 0


@dataclass
class CrawlSignals:
    crawl_success: bool = False
    page_title: str = ""
    meta_description: str = ""
    language: str = ""
    feeds: list[FeedInfo] = field(default_factory=list)
    json_ld_types: list[str] = field(default_factory=list)
    internal_links_count: int = 0
    article_like_paths: int = 0
    has_date_patterns: bool = False
    sections: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    location: Location = field(default_factory=Location)
    content_snippet: str = ""
    robots_txt: RobotsTxt = field(default_factory=RobotsTxt)
    llm_signals: LLMSignals | None = None

    @property
    def rss_feeds(self) -> list[str]:
        """URLs of feeds that were confirmed to parse and carry entries.

        A property, not a field, so `asdict()` serialises the full `feeds`
        records rather than a lossy URL list.
        """
        return [f.url for f in self.feeds if f.valid]


@dataclass
class ClassificationResult:
    classification: str = "REJECT"
    confidence: float = 0.0
    reason: str = ""


@dataclass
class ScoringResult:
    score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    polling_tier: str = ""


@dataclass
class Candidate:
    domain: str = ""
    url: str = ""
    homepage_url: str = ""
    title: str = ""
    description: str = ""
    queries: list[str] = field(default_factory=list)
    search_occurrences: int = 0
    signals: CrawlSignals | None = None
    classification: ClassificationResult | None = None
    scoring: ScoringResult | None = None
