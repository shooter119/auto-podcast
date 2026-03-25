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


def extract_event_tokens(title: str) -> list[str]:
    """
    提取文章标题中的事件语义词（保留关键球队名、球员名、数字）。
    用于生成事件指纹，区分'同一事件的不同报道'和'完全不同的新闻'。
    """
    text = title.lower()
    # 提取数字（比分、日期等）- 有强语义
    numbers = re.findall(r"\d+", text)
    # 提取球队名/球员名（常见英文词汇，normalize_title 会去掉但这里保留）
    # 先做一次轻度 normalize（只去标点，不去停用词）
    cleaned = re.sub(r"[^\w\s]", " ", text)
    tokens = cleaned.split()
    # 停用词：只去掉极通用的词，保留有语义的词
    SOFT_STOPWORDS = {
        "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "but",
        "is", "are", "was", "were", "be", "been", "being",
        "that", "this", "it", "its",
        "with", "from", "by", "as",
        "latest", "breaking", "live", "update", "news",
    }
    semantic_tokens = [t for t in tokens if t not in SOFT_STOPWORDS and len(t) > 2]
    # 合并数字（作为字符串保留）
    result = semantic_tokens + [f"n{n}" for n in numbers]
    return result


def event_fingerprint(title: str, event_type: str) -> str:
    """
    事件指纹：只基于语义词，不依赖 URL。
    同一个事件的不同报道（不同来源、不同措辞）应有相同或极相似的指纹。
    例如："Arsenal beat Man City 3-1" 和 "Arsenal 3-1 victory over Man City"
    应该被判定为'同一事件的不同报道'，而不是'重复'。
    """
    tokens = extract_event_tokens(title)
    # 按字母排序，保证顺序一致
    tokens.sort()
    normalized = f"{event_type}|" + "|".join(tokens)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def extract_domain(url: str) -> str:
    parts = urlsplit(url)
    return parts.netloc.lower()


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return any(lowered == prefix or lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
