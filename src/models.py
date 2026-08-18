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
    has_rss: bool = False
    site_description: str = ""


@dataclass
class CrawlSignals:
    crawl_success: bool = False
    page_title: str = ""
    meta_description: str = ""
    language: str = ""
    rss_feeds: list[str] = field(default_factory=list)
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
    title: str = ""
    description: str = ""
    queries: list[str] = field(default_factory=list)
    search_occurrences: int = 0
    signals: CrawlSignals | None = None
    classification: ClassificationResult | None = None
    scoring: ScoringResult | None = None
