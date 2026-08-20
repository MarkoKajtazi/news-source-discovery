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

LOCAL_NEWS_TERMS: dict[str, list[str]] = {
    "North Macedonia": ["вести", "весник", "портал", "дневник"],
    "Serbia": ["вести", "новине", "новости"],
    "Croatia": ["vijesti", "novine", "portal"],
    "Bosnia and Herzegovina": ["vijesti", "novine"],
    "Slovenia": ["novice", "časopis"],
    "Bulgaria": ["новини", "вестник"],
    "Albania": ["lajme", "gazetë"],
    "Kosovo": ["lajme", "gazetë"],
    "Greece": ["ειδήσεις", "εφημερίδα"],
    "Turkey": ["haberler", "gazete"],
    "Germany": ["Nachrichten", "Zeitung"],
    "France": ["actualités", "journal"],
    "Spain": ["noticias", "periódico"],
    "Italy": ["notizie", "giornale"],
    "Portugal": ["notícias", "jornal"],
    "Netherlands": ["nieuws", "krant"],
    "Poland": ["wiadomości", "gazeta"],
    "Romania": ["știri", "ziar"],
    "Czech Republic": ["zprávy", "noviny"],
    "Hungary": ["hírek", "újság"],
    "Sweden": ["nyheter", "tidning"],
    "Norway": ["nyheter", "avis"],
    "Denmark": ["nyheder", "avis"],
    "Finland": ["uutiset", "sanomalehti"],
    "Ukraine": ["новини", "газета"],
    "Russia": ["новости", "газета"],
    "Japan": ["ニュース", "新聞"],
    "South Korea": ["뉴스", "신문"],
    "China": ["新闻", "报纸"],
    "India": ["समाचार", "अखबार"],
    "Brazil": ["notícias", "jornal"],
    "Mexico": ["noticias", "periódico"],
    "Argentina": ["noticias", "diario"],
    "Egypt": ["أخبار", "جريدة"],
    "Saudi Arabia": ["أخبار", "جريدة"],
    "Iran": ["اخبار", "روزنامه"],
    "Israel": ["חדשות", "עיתון"],
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
    "North Macedonia": [".mk"],
    "Serbia": [".rs"],
    "Croatia": [".hr"],
    "Bosnia and Herzegovina": [".ba"],
    "Slovenia": [".si"],
    "Bulgaria": [".bg"],
    "Albania": [".al"],
    "Kosovo": [".xk"],
    "Greece": [".gr"],
    "Turkey": [".tr"],
    "Germany": [".de"],
    "France": [".fr"],
    "Spain": [".es"],
    "Italy": [".it"],
    "Portugal": [".pt"],
    "Netherlands": [".nl"],
    "Poland": [".pl"],
    "Romania": [".ro"],
    "Czech Republic": [".cz"],
    "Hungary": [".hu"],
    "Sweden": [".se"],
    "Norway": [".no"],
    "Denmark": [".dk"],
    "Finland": [".fi"],
    "Ukraine": [".ua"],
    "Russia": [".ru"],
    "Japan": [".jp"],
    "South Korea": [".kr"],
    "China": [".cn"],
    "India": [".in"],
    "Brazil": [".br"],
    "Mexico": [".mx"],
    "Argentina": [".ar"],
    "Egypt": [".eg"],
    "Saudi Arabia": [".sa"],
    "Iran": [".ir"],
    "Israel": [".il"],
    "England": [".uk", ".co.uk"],
    "United Kingdom": [".uk", ".co.uk"],
    "United States": [".us"],
}

COUNTRY_LANGUAGES: dict[str, list[str]] = {
    "North Macedonia": ["mk", "sq"],
    "Serbia": ["sr"],
    "Croatia": ["hr"],
    "Bosnia and Herzegovina": ["bs", "hr", "sr"],
    "Slovenia": ["sl"],
    "Bulgaria": ["bg"],
    "Albania": ["sq"],
    "Kosovo": ["sq", "sr"],
    "Greece": ["el"],
    "Turkey": ["tr"],
    "Germany": ["de"],
    "France": ["fr"],
    "Spain": ["es"],
    "Italy": ["it"],
    "Portugal": ["pt"],
    "Netherlands": ["nl"],
    "Poland": ["pl"],
    "Romania": ["ro"],
    "Czech Republic": ["cs"],
    "Hungary": ["hu"],
    "Sweden": ["sv"],
    "Norway": ["no", "nb", "nn"],
    "Denmark": ["da"],
    "Finland": ["fi"],
    "Ukraine": ["uk"],
    "Russia": ["ru"],
    "Japan": ["ja"],
    "South Korea": ["ko"],
    "China": ["zh"],
    "India": ["hi", "en"],
    "Brazil": ["pt"],
    "Mexico": ["es"],
    "Argentina": ["es"],
    "Egypt": ["ar"],
    "Saudi Arabia": ["ar"],
    "Iran": ["fa"],
    "Israel": ["he"],
    "England": ["en"],
    "United Kingdom": ["en"],
    "United States": ["en"],
}
