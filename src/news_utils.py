from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "igshid",
    "mc_",
    "mkt_",
    "ref",
    "source",
)

TITLE_STOPWORDS = {
    "arsenal",
    "fc",
    "latest",
    "news",
    "report",
    "official",
    "premier",
    "league",
    "breaking",
    "live",
    "update",
    "vs",
    "the",
    "a",
    "an",
}


def normalize_url(url: str) -> str:
    if not url:
        return ""

    parts = urlsplit(url.strip())
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if not _is_tracking_param(key)
    ]
    normalized_query = urlencode(sorted(query_items))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, normalized_query, ""))


def normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff\s]", " ", text)
    tokens = [token for token in text.split() if token and token not in TITLE_STOPWORDS]
    return " ".join(tokens)


def build_fingerprint(title: str, url: str, event_type: str) -> str:
    normalized = f"{event_type}|{normalize_title(title)}|{normalize_url(url)}"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def extract_domain(url: str) -> str:
    parts = urlsplit(url)
    return parts.netloc.lower()


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return any(lowered == prefix or lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
