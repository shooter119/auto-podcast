from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.news_utils import build_fingerprint, extract_domain, normalize_title, normalize_url

logger = logging.getLogger(__name__)


def deduplicate(articles: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    dedup_config = config.get("dedup", {})
    history_path = Path(dedup_config.get("history_file", "output/history.json"))
    similarity_threshold = float(dedup_config.get("similarity_threshold", 0.86))
    fallback_keep = int(dedup_config.get("fallback_keep", 2))
    cooldowns = {
        "match": int(dedup_config.get("cooldown_match_hours", 48)),
        "transfer": int(dedup_config.get("cooldown_transfer_hours", 36)),
        "injury": int(dedup_config.get("cooldown_news_hours", 18)),
        "news": int(dedup_config.get("cooldown_news_hours", 18)),
    }

    history = _load_history(history_path)
    now = datetime.now(timezone.utc)
    max_cooldown = max(cooldowns.values())
    active_history = [
        entry for entry in history
        if now - _parse_timestamp(entry.get("timestamp")) < timedelta(hours=max_cooldown)
    ]

    filtered: list[dict[str, Any]] = []
    new_entries: list[dict[str, Any]] = []
    duplicate_reasons: list[str] = []

    for article in articles:
        normalized = _prepare_article(article)
        cooldown_hours = cooldowns.get(normalized["event_type"], cooldowns["news"])

        matched_reason = _find_duplicate_reason(normalized, active_history, cooldown_hours, similarity_threshold, now)
        if matched_reason:
            duplicate_reasons.append(f"{article['title'][:60]} -> {matched_reason}")
            logger.info("去重跳过: %s (%s)", article["title"][:80], matched_reason)
            continue

        filtered.append(normalized)
        new_entry = {
            "title": normalized["title"],
            "url": normalized["url"],
            "type": normalized["event_type"],
            "timestamp": now.isoformat(),
            "normalized_title": normalized["normalized_title"],
            "fingerprint": normalized["fingerprint"],
            "source_domain": normalized["source_domain"],
            "event_type": normalized["event_type"],
        }
        new_entries.append(new_entry)
        active_history.append(new_entry)

    if not filtered and articles:
        fallback = _fallback_articles(articles, fallback_keep)
        logger.warning("所有候选都被历史去重命中，回退保留 %d 条高优先级新闻", len(fallback))
        filtered = [_prepare_article(article) for article in fallback]

    _save_history(active_history, history_path)
    logger.info("去重: %d -> %d 条新闻", len(articles), len(filtered))
    if duplicate_reasons:
        logger.info("去重摘要: %s", " | ".join(duplicate_reasons[:5]))
    return filtered


def _prepare_article(article: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(article)
    prepared["url"] = normalize_url(article.get("url", ""))
    prepared["normalized_title"] = normalize_title(article.get("title", ""))
    prepared["event_type"] = article.get("news_type") or _classify_news(article.get("title", ""))
    prepared["fingerprint"] = build_fingerprint(prepared["title"], prepared["url"], prepared["event_type"])
    prepared["source_domain"] = article.get("source_domain") or extract_domain(prepared["url"])
    return prepared


def _find_duplicate_reason(
    article: dict[str, Any],
    history: list[dict[str, Any]],
    cooldown_hours: int,
    similarity_threshold: float,
    now: datetime,
) -> str | None:
    for entry in history:
        entry_time = _parse_timestamp(entry.get("timestamp"))
        if now - entry_time > timedelta(hours=cooldown_hours):
            continue
        if entry.get("fingerprint") == article["fingerprint"]:
            return "事件指纹重复"
        if normalize_url(entry.get("url", "")) == article["url"]:
            return "规范化 URL 重复"
        if entry.get("event_type") != article["event_type"]:
            continue
        if entry.get("source_domain") == article["source_domain"]:
            similarity = _title_similarity(article["normalized_title"], entry.get("normalized_title", ""))
            if similarity >= similarity_threshold:
                return f"同源标题高度相似 {similarity:.2f}"
    return None


def _load_history(history_path: Path) -> list[dict[str, Any]]:
    if history_path.exists():
        try:
            with open(history_path, encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            logger.warning("历史记录文件损坏，重新创建")
    return []


def _save_history(history: list[dict[str, Any]], history_path: Path) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "w", encoding="utf-8") as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2)


def _classify_news(title: str) -> str:
    title_lower = title.lower()
    if any(keyword in title_lower for keyword in ["match", "score", "goal", "win", "lose", "draw", "fixture", "比赛", "进球", "胜", "负", "平", "首发"]):
        return "match"
    if any(keyword in title_lower for keyword in ["transfer", "sign", "deal", "bid", "fee", "loan", "转会", "签约", "租借", "报价"]):
        return "transfer"
    if any(keyword in title_lower for keyword in ["injury", "fitness", "return", "伤病", "缺阵", "复出"]):
        return "injury"
    return "news"


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fallback_articles(articles: list[dict[str, Any]], fallback_keep: int) -> list[dict[str, Any]]:
    ranked = sorted(
        articles,
        key=lambda item: (
            int(item.get("tier", "3")),
            float(item.get("relevance_score", 0.0)),
            float(item.get("freshness_score", 0.0)),
            float(item.get("ranking_score", 0.0)),
        ),
        reverse=True,
    )
    return ranked[: max(fallback_keep, 1)]
