from src.config import (
    COUNTRY_LANGUAGES,
    COUNTRY_TLDS,
    POLLING_TIERS,
    SCORING_WEIGHTS as WEIGHTS,
)
from src.models import Candidate, CrawlSignals, ScoringResult


def _score_tld(domain: str, country: str) -> float:
    tlds = COUNTRY_TLDS.get(country, [])
    if not tlds:
        return 0.0
    for tld in tlds:
        if domain.endswith(tld):
            return WEIGHTS["tld_match"]
    return 0.0


def _score_language(signals: CrawlSignals, country: str) -> float:
    lang = signals.language.lower().strip()
    if not lang:
        return 0.0
    expected = COUNTRY_LANGUAGES.get(country, [])
    if not expected:
        return 0.0
    for code in expected:
        if lang == code or lang.startswith(code + "-"):
            return WEIGHTS["language_match"]
    return 0.0


def _score_occurrences(occurrences: int) -> float:
    # 1 occurrence = 3pts, caps at 5+ = 15pts
    return min(occurrences * 3, WEIGHTS["search_occurrences"])


def _score_rss(signals: CrawlSignals) -> float:
    if signals.rss_feeds:
        return WEIGHTS["rss_available"]
    return 0.0


def _score_article_paths(signals: CrawlSignals) -> float:
    count = signals.article_like_paths
    if count >= 20:
        return WEIGHTS["article_paths"]
    if count >= 10:
        return WEIGHTS["article_paths"] * 0.7
    if count >= 3:
        return WEIGHTS["article_paths"] * 0.4
    if count >= 1:
        return WEIGHTS["article_paths"] * 0.2
    return 0.0


def _score_sections(signals: CrawlSignals) -> float:
    count = len(signals.sections)
    if count >= 5:
        return WEIGHTS["sections"]
    if count >= 2:
        return WEIGHTS["sections"] * 0.5
    return 0.0


def _score_dates(signals: CrawlSignals) -> float:
    return WEIGHTS["has_dates"] if signals.has_date_patterns else 0.0


def _score_authors(signals: CrawlSignals) -> float:
    return WEIGHTS["has_authors"] if signals.authors else 0.0


def _score_confidence(candidate: Candidate) -> float:
    if not candidate.classification:
        return 0.0
    return candidate.classification.confidence * WEIGHTS["classification_confidence"]


def _score_location(signals: CrawlSignals, city: str | None, country: str) -> float:
    loc = signals.location
    if not loc.name and not loc.country:
        return 0.0
    name_lower = loc.name.lower()
    country_lower = loc.country.lower()
    if city and city.lower() in name_lower:
        return WEIGHTS["location_match"]
    if country.lower() in country_lower or country.lower() in name_lower:
        return WEIGHTS["location_match"] * 0.6
    return 0.0


def _get_polling_tier(score: float) -> str:
    for threshold, tier, _ in POLLING_TIERS:
        if score >= threshold:
            return tier
    return "backup"


def score_candidate(candidate: Candidate, city: str | None, country: str) -> Candidate:
    """Score a single candidate based on relevance signals."""
    signals = candidate.signals or CrawlSignals()
    breakdown = {}

    breakdown["tld_match"] = _score_tld(candidate.domain, country)
    breakdown["language_match"] = _score_language(signals, country)
    breakdown["search_occurrences"] = _score_occurrences(candidate.search_occurrences)
    breakdown["rss_available"] = _score_rss(signals)
    breakdown["article_paths"] = _score_article_paths(signals)
    breakdown["sections"] = _score_sections(signals)
    breakdown["has_dates"] = _score_dates(signals)
    breakdown["has_authors"] = _score_authors(signals)
    breakdown["classification_confidence"] = _score_confidence(candidate)
    breakdown["location_match"] = _score_location(signals, city, country)

    candidate.scoring = ScoringResult(
        score=round(sum(breakdown.values()), 2),
        breakdown=breakdown,
    )
    return candidate


def _normalize_scores(candidates: list[Candidate]):
    """Normalize raw scores to 0-100 based on the batch max."""
    scored = [c for c in candidates if c.scoring and c.scoring.polling_tier != "rejected"]
    if not scored:
        return
    max_score = max(c.scoring.score for c in scored)
    if max_score <= 0:
        return
    for c in scored:
        c.scoring.score = round(c.scoring.score / max_score * 100, 2)
        c.scoring.polling_tier = _get_polling_tier(c.scoring.score)


def score_candidates(candidates: list[Candidate], city: str | None, country: str) -> list[Candidate]:
    """Score and rank all classified candidates."""
    print(f"\nScoring {len(candidates)} candidates...\n")

    for candidate in candidates:
        if not candidate.classification or candidate.classification.classification == "REJECT":
            candidate.scoring = ScoringResult(
                score=0.0,
                breakdown={},
                polling_tier="rejected",
            )
            continue
        score_candidate(candidate, city, country)

    _normalize_scores(candidates)

    scored = [c for c in candidates if c.scoring and c.scoring.polling_tier != "rejected"]
    scored.sort(key=lambda c: c.scoring.score, reverse=True)

    for c in scored:
        print(f"  {c.domain:<35} score={c.scoring.score:5.1f}  tier={c.scoring.polling_tier}")

    tier_counts = {}
    for c in scored:
        tier = c.scoring.polling_tier
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    rejected = sum(1 for c in candidates if c.scoring and c.scoring.polling_tier == "rejected")
    print(f"\n  Tiers: {tier_counts}")
    print(f"  Rejected (not scored): {rejected}\n")

    return candidates
