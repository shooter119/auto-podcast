from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.news_utils import build_fingerprint, event_fingerprint, extract_domain, normalize_title, normalize_url

logger = logging.getLogger(__name__)


def deduplicate(articles: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    dedup_config = config.get("dedup", {})
    history_path = Path(dedup_config.get("history_file", "output/history.json"))
    similarity_threshold = float(dedup_config.get("similarity_threshold", 0.86))
    fallback_keep = int(dedup_config.get("fallback_keep", 2))
    cooldowns = {
        "match": int(dedup_config.get("cooldown_match_hours", 72)),
        "transfer": int(dedup_config.get("cooldown_transfer_hours", 168)),
        "injury": int(dedup_config.get("cooldown_injury_hours", 120)),
        "news": int(dedup_config.get("cooldown_news_hours", 36)),
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
            "event_fp": normalized["event_fp"],
            "source_domain": normalized["source_domain"],
            "event_type": normalized["event_type"],
            # TTL（秒）：按类型区分，过期后不再用于去重
            # 调研建议：match=72h(英超/杯赛), transfer=168h(7天), injury=120h(5天), news=36h(2天)
            "ttl": {
                "match": 72 * 3600,
                "transfer": 168 * 3600,
                "injury": 120 * 3600,
                "news": 36 * 3600,
            }.get(normalized["event_type"], 36 * 3600),
        }
        new_entries.append(new_entry)
        active_history.append(new_entry)

    if not filtered and articles:
        fallback = _fallback_articles(articles, fallback_keep, active_history)
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
    event_type = article.get("news_type") or _classify_news(article.get("title", ""))
    prepared["event_type"] = event_type
    prepared["fingerprint"] = build_fingerprint(prepared["title"], prepared["url"], event_type)
    # 事件指纹：区分'同一事件的不同报道'和'完全不同的新闻'
    prepared["event_fp"] = event_fingerprint(prepared["title"], event_type)
    prepared["source_domain"] = article.get("source_domain") or extract_domain(prepared["url"])
    return prepared


def _find_duplicate_reason(
    article: dict[str, Any],
    history: list[dict[str, Any]],
    cooldown_hours: int,
    similarity_threshold: float,
    now: datetime,
) -> str | None:
    """
    判断文章是否重复。
    
    去重逻辑（两极）：
    1. fingerprint 完全相同（URL + 标题 + 类型）→ 跳过（同一篇文章）
    2. event_fp 相同（同事件的不同报道）→ 用相似度判断：
       - 相似度 ≥ 阈值 → 跳过（同一事件、相似报道）
       - 相似度 < 阈值 → 保留（同一事件、不同角度报道）
    3. 历史中没有 event_fp 字段（旧格式）→ 降级用 URL + fingerprint 判断
    
    关键改进：不再把'同一事件的不同角度报道'当作重复。
    """
    for entry in history:
        entry_time = _parse_timestamp(entry.get("timestamp"))

        entry_ttl_seconds = entry.get("ttl")
        if entry_ttl_seconds is None:
            event_type = entry.get("event_type", "news")
            entry_ttl_seconds = {
                "match": 72 * 3600,
                "transfer": 168 * 3600,
                "injury": 120 * 3600,
                "news": 36 * 3600,
            }.get(event_type, 36 * 3600)

        entry_ttl_hours = entry_ttl_seconds / 3600
        if now - entry_time > timedelta(hours=entry_ttl_hours):
            continue

        # 1. 精确去重：fingerprint 相同（URL + 标题完全一致）
        if entry.get("fingerprint") == article.get("fingerprint"):
            return "同一文章（fingerprint 重复）"

        # 2. URL 去重
        if normalize_url(entry.get("url", "")) == normalize_url(article.get("url", "")):
            return "URL 重复"

        # 3. 事件指纹去重（核心改进）
        # 有 event_fp 字段时：同事件 → 用相似度判断
        if "event_fp" in entry and article.get("event_fp"):
            if entry["event_fp"] == article["event_fp"]:
                # 同事件：检查相似度
                similarity = _title_similarity(
                    article.get("normalized_title", ""),
                    entry.get("normalized_title", ""),
                )
                if similarity >= similarity_threshold:
                    return f"同事件高度相似 {similarity:.2f}"
                # 相似度低 → 不同角度报道，保留

        # 4. 旧格式（无 event_fp）：用事件类型 + 来源 + 相似度兜底
        if "event_fp" not in entry:
            if entry.get("event_type") == article.get("event_type"):
                if entry.get("source_domain") == article.get("source_domain"):
                    similarity = _title_similarity(
                        article.get("normalized_title", ""),
                        entry.get("normalized_title", ""),
                    )
                    if similarity >= similarity_threshold:
                        return f"同源同类型标题相似 {similarity:.2f}"

    return None


def _load_history(history_path: Path) -> list[dict[str, Any]]:
    """
    加载历史记录，同时清理已过期条目。
    每条记录的 TTL 由其 event_type 决定，过期则丢弃。
    """
    if not history_path.exists():
        return []

    try:
        with open(history_path, encoding="utf-8") as handle:
            data = json.load(handle)
        entries = data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        logger.warning("历史记录文件损坏，重新创建")
        return []

    # 按 TTL 过滤（清理过期条目）
    now = datetime.now(timezone.utc)
    EVENT_TTL = {
        "match": 72 * 3600,
        "transfer": 48 * 3600,
        "injury": 24 * 3600,
        "news": 18 * 3600,
    }

    def is_valid(entry: dict[str, Any]) -> bool:
        entry_ttl = entry.get("ttl")
        if entry_ttl is None:
            # 旧格式：用 event_type 推断
            entry_ttl = EVENT_TTL.get(entry.get("event_type", "news"), 18 * 3600)
        entry_time = _parse_timestamp(entry.get("timestamp"))
        return (now - entry_time).total_seconds() <= entry_ttl

    valid_entries = [e for e in entries if is_valid(e)]
    removed = len(entries) - len(valid_entries)
    if removed > 0:
        logger.info(f"历史记录: 清理 {removed} 条过期条目，剩余 {len(valid_entries)} 条")

    return valid_entries


def _save_history(history: list[dict[str, Any]], history_path: Path) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "w", encoding="utf-8") as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2)


def _classify_news(title: str) -> str:
    title_lower = title.lower()
    if any(keyword in title_lower for keyword in ["match", "score", "goal", "win", "lose", "draw", "fixture", "beat", "victory", "defeat", "比赛", "进球", "胜", "负", "平", "首发"]):
        return "match"
    if any(keyword in title_lower for keyword in ["transfer", "sign", "deal", "bid", "fee", "loan", "转会", "签约", "租借", "报价"]):
        return "transfer"
    if any(keyword in title_lower for keyword in ["injury", "fitness", "return", "伤病", "缺阵", "复出"]):
        return "injury"
    # FA Cup / Carabao Cup 比赛 → match 类型，享受较长 TTL
    if any(keyword in title_lower for keyword in ["fa cup", "facup", "carabao cup", "联赛杯", "足总杯"]):
        return "match"
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


def _fallback_articles(
    articles: list[dict[str, Any]],
    fallback_keep: int,
    history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    当所有候选都被去重跳过时的兜底策略：
    - 优先 arsenal_core 分组的文章（阿森纳主菜）
    - 其次 rivals、league 分组
    - 只返回不在历史记录中的文章（避免 fallback 重复历史）
    - 同组内按 tier + 相关性 + 新鲜度排序
    """
    GROUP_PRIORITY = {"arsenal_core": 3, "rivals": 2, "league": 1, "league_tail": 1}

    # 构建历史指纹集合，快速判断是否已在历史
    history_fps = {e.get("fingerprint") for e in (history or []) if e.get("fingerprint")}
    history_urls = {normalize_url(e.get("url", "")) for e in (history or []) if e.get("url")}

    def fallback_score(item: dict[str, Any]) -> tuple:
        group = item.get("group", "")
        group_priority = GROUP_PRIORITY.get(group, 0)
        return (
            group_priority,
            int(item.get("tier", "3")),
            float(item.get("relevance_score", 0.0)),
            float(item.get("freshness_score", 0.0)),
            float(item.get("ranking_score", 0.0)),
        )

    # 过滤：只保留不在历史中的文章
    def not_in_history(item: dict[str, Any]) -> bool:
        fp = item.get("fingerprint")
        url = normalize_url(item.get("url", ""))
        # 已在历史则跳过
        if fp and fp in history_fps:
            return False
        if url and url in history_urls:
            return False
        return True

    filtered = [a for a in articles if not_in_history(a)]
    if not filtered:
        # 历史中找不到任何新文章 → 宽松兜底：取评分最高且arsenal_core优先的
        logger.warning("fallback: 所有文章均已在历史中，宽松兜底取 top %d", fallback_keep)
        filtered = articles

    ranked = sorted(filtered, key=fallback_score, reverse=True)
    return ranked[: max(fallback_keep, 1)]
