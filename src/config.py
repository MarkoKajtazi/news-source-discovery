OUTPUT_DIR = "output"

QUERY_TEMPLATES = [
    "{city} news",
    "{city} newspaper",
    "{city} local news",
    "{country} news website",
    "{country} national newspaper",
    "{country} news agency",
    "{country} online news portal",
    "top news sites in {country}",
    "most read newspaper {country}",
    "reliable news source {country}",
    "list of newspapers in {city}",
]

COUNTRY_ONLY_TEMPLATES = [
    "{country} news website",
    "{country} national newspaper",
    "{country} news agency",
    "{country} online news portal",
    "top news sites in {country}",
    "most read newspaper {country}",
    "reliable news source {country}",
]

# Every country dict below is keyed on ISO 3166-1 alpha-2, matching the primary
# key of the .NET `Country` table. Country *names* are never used as keys: the
# app's two seed CSVs spell the same country differently ("North Macedonia" vs
# "Macedonia, The former Yugoslav Rep. of"), so a name-keyed lookup cannot
# reliably hit. Names arrive on the request and are only ever query text.
LOCAL_NEWS_TERMS: dict[str, list[str]] = {
    "MK": ["вести", "весник", "портал", "дневник"],
    "RS": ["вести", "новине", "новости"],
    "HR": ["vijesti", "novine", "portal"],
    "BA": ["vijesti", "novine"],
    "SI": ["novice", "časopis"],
    "BG": ["новини", "вестник"],
    "AL": ["lajme", "gazetë"],
    "XK": ["lajme", "gazetë"],
    "GR": ["ειδήσεις", "εφημερίδα"],
    "TR": ["haberler", "gazete"],
    "DE": ["Nachrichten", "Zeitung"],
    "FR": ["actualités", "journal"],
    "ES": ["noticias", "periódico"],
    "IT": ["notizie", "giornale"],
    "PT": ["notícias", "jornal"],
    "NL": ["nieuws", "krant"],
    "PL": ["wiadomości", "gazeta"],
    "RO": ["știri", "ziar"],
    "CZ": ["zprávy", "noviny"],
    "HU": ["hírek", "újság"],
    "SE": ["nyheter", "tidning"],
    "NO": ["nyheter", "avis"],
    "DK": ["nyheder", "avis"],
    "FI": ["uutiset", "sanomalehti"],
    "UA": ["новини", "газета"],
    "RU": ["новости", "газета"],
    "JP": ["ニュース", "新聞"],
    "KR": ["뉴스", "신문"],
    "CN": ["新闻", "报纸"],
    "IN": ["समाचार", "अखबार"],
    "BR": ["notícias", "jornal"],
    "MX": ["noticias", "periódico"],
    "AR": ["noticias", "diario"],
    "EG": ["أخبار", "جريدة"],
    "SA": ["أخبار", "جريدة"],
    "IR": ["اخبار", "روزنامه"],
    "IL": ["חדשות", "עיתון"],
}

REJECTED_DOMAINS = {
    # Social media
    "facebook.com", "twitter.com", "x.com", "instagram.com", "tiktok.com",
    "linkedin.com", "reddit.com", "threads.net", "mastodon.social",
    "pinterest.com", "snapchat.com", "tumblr.com",
    # Video platforms
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv",
    # E-commerce
    "amazon.com", "ebay.com", "aliexpress.com", "alibaba.com", "etsy.com",
    "shopify.com", "walmart.com",
    # Search engines / aggregators
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "yandex.com",
    "baidu.com",
    # Wikipedia (not a news source)
    "wikipedia.org", "wikimedia.org",
    # Misc
    "github.com", "stackoverflow.com", "medium.com", "substack.com",
    "quora.com", "archive.org",
}

REJECTED_PATTERNS = [
    r"\.gov(\.[a-z]{2})?$",
    r"\.edu(\.[a-z]{2})?$",
]


OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/chat"
MODEL = "gpt-oss:120b-cloud"

# Homepage markdown is truncated before being sent for extraction.
LLM_EXTRACTION_MAX_CHARS = 12000

SYSTEM_PROMPT = """\
You are a news source classifier. You will receive information about a website \
that was discovered while searching for news sources in a specific location. \
Based on the signals provided, classify the website into exactly one of three categories:

1. NEWS_SOURCE — A website that directly publishes news articles. \
Examples: newspapers, news agencies, TV/radio station news sites, online-only news portals. \
Must produce original journalistic content on a regular basis.

2. DISCOVERY_SOURCE — A website that is not itself a news source, but is useful \
for discovering news sources. Examples: newspaper directories, media lists, \
press freedom indexes, journalism organizations, Wikipedia/wiki pages listing media outlets.

3. REJECT — A website that is neither a news source nor useful for discovering them. \
Examples: hotels, tourism sites, app stores, SEO tools, government portals, \
academic papers, e-commerce, social media, encyclopedias (unless listing media).

Weigh feed evidence heavily — every feed listed has been fetched and parsed, so \
its entry counts and dates are facts, not guesses:
- A feed with recent entries that originate on the site's own domain, from a \
single outlet, is strong evidence of NEWS_SOURCE.
- A feed whose entries mostly originate OFF the site's own domain, or that names \
many distinct originating outlets, means the site republishes other people's \
reporting. Classify it DISCOVERY_SOURCE, not NEWS_SOURCE, however much it looks \
like a news portal. One originating outlet means a publisher; dozens means an \
aggregator.
- "headlines only" feeds combined with a high off-domain ratio point the same \
way: aggregator, so DISCOVERY_SOURCE.
- No valid feed is weak evidence at most. Plenty of real news sites publish none.

Likewise treat an LLM analysis of content_type "news_aggregator", or \
"Has original articles: False", as strong evidence for DISCOVERY_SOURCE rather \
than NEWS_SOURCE.

Respond with a JSON object containing exactly these fields:
- "classification": one of "NEWS_SOURCE", "DISCOVERY_SOURCE", or "REJECT"
- "confidence": a number from 0.0 to 1.0
- "reason": a brief explanation (one sentence)

Respond ONLY with the JSON object, no other text."""

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "string",
            "enum": ["NEWS_SOURCE", "DISCOVERY_SOURCE", "REJECT"],
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["classification", "confidence", "reason"],
}

LLM_EXTRACTION_INSTRUCTION = """\
You analyze website homepages and extract structured information about them. \
The website may be in any language — analyze the actual content regardless of language.

Respond with a JSON object containing exactly these fields:
- "is_news_site": boolean — does this website publish news articles?
- "has_original_articles": boolean — does it publish original reporting, or \
does it only aggregate and link to other sources?
- "language": string — ISO 639-1 code of the content, e.g. "mk", "en", "ru"
- "content_type": one of "news_portal", "news_aggregator", "newspaper", \
"tv_station", "radio_station", "blog", "directory", "government", "other"
- "sections": array of strings — editorial sections/categories found on the \
site, e.g. ["politics", "sport", "economy"]
- "site_description": string — one sentence describing what the site is about

Use exactly these field names. Respond ONLY with the JSON object, no other text."""

LLM_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_news_site": {
            "type": "boolean",
            "description": "Whether this website publishes news content",
        },
        "has_original_articles": {
            "type": "boolean",
            "description": "Whether the site publishes original articles vs just aggregating links",
        },
        "language": {
            "type": "string",
            "description": "ISO 639-1 language code of the content (e.g. mk, en, ru, sq)",
        },
        "content_type": {
            "type": "string",
            "enum": ["news_portal", "news_aggregator", "newspaper", "tv_station", "radio_station", "blog", "directory", "government", "other"],
        },
        "sections": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Editorial sections/categories found on the site",
        },
        "site_description": {
            "type": "string",
            "description": "One sentence describing what this website is about",
        },
    },
    "required": ["is_news_site", "has_original_articles", "language", "content_type", "sections", "site_description"],
}

# Probed when a homepage's <head> exposes no feed links.
FEED_PATHS = [
    "/feed",
    "/rss",
    "/rss.xml",
    "/feed.xml",
    "/atom.xml",
    "/index.xml",
]

# WordPress comment feeds carry no articles — useless for ingestion.
FEED_URL_BLOCKLIST = ["/comments/feed"]

# Feed validation. A nominated URL is only kept once it has been fetched and
# parsed as a real feed carrying entries — HTTP 200 alone proves nothing, some
# sites serve text/html for /rss instead of a 404.
FEED_FETCH_TIMEOUT = 10.0
FEED_MAX_BYTES = 2_000_000
FEED_MAX_PER_CANDIDATE = 3
FEED_MIN_ENTRIES = 1
# Entry ages used by the scorer to grade feed freshness (days).
FEED_FRESH_DAYS = 2
FEED_RECENT_DAYS = 7
FEED_STALE_DAYS = 30

SCORING_WEIGHTS = {
    "tld_match": 15,
    "language_match": 15,
    "search_occurrences": 15,
    "rss_available": 10,
    "article_paths": 15,
    "sections": 5,
    "has_dates": 5,
    "has_authors": 5,
    "classification_confidence": 10,
    "location_match": 5,
}

POLLING_TIERS = [
    (80, "high",   "poll every 15 min"),
    (50, "medium", "poll every 1 hour"),
    (20, "low",    "poll every 6 hours"),
    (0,  "backup", "no scheduled polling"),
]

COUNTRY_TLDS: dict[str, list[str]] = {
    "MK": [".mk"],
    "RS": [".rs"],
    "HR": [".hr"],
    "BA": [".ba"],
    "SI": [".si"],
    "BG": [".bg"],
    "AL": [".al"],
    "XK": [".xk"],
    "GR": [".gr"],
    "TR": [".tr"],
    "DE": [".de"],
    "FR": [".fr"],
    "ES": [".es"],
    "IT": [".it"],
    "PT": [".pt"],
    "NL": [".nl"],
    "PL": [".pl"],
    "RO": [".ro"],
    "CZ": [".cz"],
    "HU": [".hu"],
    "SE": [".se"],
    "NO": [".no"],
    "DK": [".dk"],
    "FI": [".fi"],
    "UA": [".ua"],
    "RU": [".ru"],
    "JP": [".jp"],
    "KR": [".kr"],
    "CN": [".cn"],
    "IN": [".in"],
    "BR": [".br"],
    "MX": [".mx"],
    "AR": [".ar"],
    "EG": [".eg"],
    "SA": [".sa"],
    "IR": [".ir"],
    "IL": [".il"],
    # Was two rows, "England" and "United Kingdom", both meaning GB.
    "GB": [".uk", ".co.uk"],
    "US": [".us"],
}

# COUNTRY_ISO2 used to live here, mapping full name -> "MK". It existed only
# to translate the pipeline's name-driven input into the codes that schema.org
# `addressCountry` / `geo.country` actually carry. The ISO code now arrives on
# the request, so the translation has already happened upstream.

COUNTRY_LANGUAGES: dict[str, list[str]] = {
    "MK": ["mk", "sq"],
    "RS": ["sr"],
    "HR": ["hr"],
    "BA": ["bs", "hr", "sr"],
    "SI": ["sl"],
    "BG": ["bg"],
    "AL": ["sq"],
    "XK": ["sq", "sr"],
    "GR": ["el"],
    "TR": ["tr"],
    "DE": ["de"],
    "FR": ["fr"],
    "ES": ["es"],
    "IT": ["it"],
    "PT": ["pt"],
    "NL": ["nl"],
    "PL": ["pl"],
    "RO": ["ro"],
    "CZ": ["cs"],
    "HU": ["hu"],
    "SE": ["sv"],
    "NO": ["no", "nb", "nn"],
    "DK": ["da"],
    "FI": ["fi"],
    "UA": ["uk"],
    "RU": ["ru"],
    "JP": ["ja"],
    "KR": ["ko"],
    "CN": ["zh"],
    "IN": ["hi", "en"],
    "BR": ["pt"],
    "MX": ["es"],
    "AR": ["es"],
    "EG": ["ar"],
    "SA": ["ar"],
    "IR": ["fa"],
    "IL": ["he"],
    "GB": ["en"],
    "US": ["en"],
}
