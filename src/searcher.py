from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.news_utils import extract_domain, normalize_url

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
GROUP_PRIORITY = {
    "arsenal_core": 30,
    "rivals": 18,
    "league": 12,
    "general": 10,
}


def _get_tier(url: str, config: dict[str, Any]) -> int:
    domain = urlparse(url).netloc.lower()
    for tier_key, tier_val in config.get("sources", {}).items():
        tier_num = int(tier_key.replace("tier", ""))
        for candidate in tier_val.get("domains", []):
            if candidate in domain:
                return tier_num
    return 2


def _collect_all_domains(config: dict[str, Any]) -> list[str]:
    domains: list[str] = []
    for tier_val in config.get("sources", {}).values():
        domains.extend(tier_val.get("domains", []))
    return domains


def _collect_keyword_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group, group_cfg in config.get("keywords", {}).items():
        if isinstance(group_cfg, list):
            group_cfg = {"queries": group_cfg}
        queries = group_cfg.get("queries", [])
        for keyword in queries:
            result.append(
                {
                    "keyword": keyword,
                    "group": group,
                    "max_results": int(group_cfg.get("max_results", config["tavily"]["max_results_per_keyword"])),
                    "final_limit": int(group_cfg.get("final_limit", group_cfg.get("max_results", 5))),
                    "restrict_to_sources": bool(group_cfg.get("restrict_to_sources", group != "arsenal_core")),
                }
            )
    return result


def _keyword_ttl(keyword: str) -> int:
    """根据关键词判断缓存 TTL（秒）"""
    kw = keyword.lower()
    if any(x in kw for x in ["injury", "fitness", "timber", "odegaard", "saka", "calle"]):
        return 4 * 3600   # 伤病：4小时
    if any(x in kw for x in ["result", "score", " win ", " lose ", " draw ", " beat", "victory", "defeat"]):
        return 6 * 3600   # 赛果：6小时
    if any(x in kw for x in ["preview", "lineup", "team news", "starting"]):
        return 6 * 3600   # 预览：6小时
    if any(x in kw for x in ["transfer", "sign", "bid", "offer", "contract"]):
        return 12 * 3600  # 转会：12小时
    if any(x in kw for x in ["press conference", "arteta", "presser"]):
        return 8 * 3600    # 发布会：8小时
    return 6 * 3600       # 默认：6小时


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    reraise=True,
)
def _tavily_search(
    api_key: str,
    keyword: str,
    max_results: int,
    include_domains: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "query": keyword,
        "topic": "news",
        "time_range": "day",
        "max_results": min(max_results, 20),
        "search_depth": "advanced",
        "include_answer": False,
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = include_domains

    response = httpx.post(
        TAVILY_SEARCH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _tavily_search_cached(
    api_key: str,
    keyword: str,
    max_results: int,
    include_domains: list[str] | None = None,
) -> dict[str, Any]:
    """
    带缓存的 Tavily 搜索。
    优先读缓存（按关键词类型设 TTL），未命中则调 API 并写入缓存。
    """
    import hashlib, json
    from pathlib import Path
    from datetime import datetime, timezone

    CACHE_DIR = Path("output/cache/search")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 生成缓存 key
    domains_str = ",".join(sorted(include_domains or []))
    key_data = f"{api_key}:{keyword}:{max_results}:{domains_str}"
    cache_key = hashlib.sha256(key_data.encode()).hexdigest()[:20]
    cache_file = CACHE_DIR / f"{cache_key}.json"

    ttl = _keyword_ttl(keyword)

    # 读缓存
    if cache_file.exists():
        try:
            entry = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(entry["cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age <= ttl:
                logger.info(f"🔵 缓存命中 [{keyword[:40]}] (TTL={ttl//3600}h)")
                return entry["data"]
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # 未命中，调 API
    data = _tavily_search(api_key, keyword, max_results, include_domains)

    # 写缓存
    try:
        entry = {
            "data": data,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "ttl": ttl,
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("缓存写入失败: %s", cache_key)

    return data


def search_news(config: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = config["tavily"]["api_key"]
    all_domains = _collect_all_domains(config)
    keyword_specs = _collect_keyword_specs(config)

    candidates: list[dict[str, Any]] = []
    best_by_url: dict[str, dict[str, Any]] = {}

    for spec in keyword_specs:
        keyword = spec["keyword"]
        group = spec["group"]
        logger.info("搜索 [%s]: %s", group, keyword)

        include_domains = all_domains if spec["restrict_to_sources"] else None
        try:
            data = _tavily_search_cached(api_key, keyword, spec["max_results"], include_domains)
        except Exception:
            logger.exception("搜索失败: %s", keyword)
            continue

        for item in data.get("results", []):
            normalized_url = normalize_url(item.get("url", ""))
            if not normalized_url:
                continue

            tier = _get_tier(normalized_url, config)
            if tier <= 2:
                logger.debug("跳过低质量来源 (tier%d): %s", tier, normalized_url)
                continue

            candidate = {
                "title": item.get("title", "").strip(),
                "url": normalized_url,
                "raw_url": item.get("url", "").strip(),
                "content": item.get("content", "").strip(),
                "summary": item.get("content", "").strip(),
                "tier": str(tier),
                "group": group,
                "score": float(item.get("score", 0.0) or 0.0),
                "published_at": item.get("published_date") or item.get("publishedAt") or "",
                "source_domain": extract_domain(normalized_url),
            }
            candidate["freshness_score"] = _freshness_score(candidate["published_at"])
            candidate["ranking_score"] = _ranking_score(candidate)

            existing = best_by_url.get(normalized_url)
            if not existing or candidate["ranking_score"] > existing["ranking_score"]:
                best_by_url[normalized_url] = candidate

    grouped_results: dict[str, list[dict[str, Any]]] = {}
    for candidate in best_by_url.values():
        grouped_results.setdefault(candidate["group"], []).append(candidate)

    final_results: list[dict[str, Any]] = []
    for spec in keyword_specs:
        group = spec["group"]
        if group not in grouped_results:
            continue
        items = grouped_results.pop(group)
        items.sort(key=lambda item: item["ranking_score"], reverse=True)
        limit = next(
            (
                candidate_spec["final_limit"]
                for candidate_spec in keyword_specs
                if candidate_spec["group"] == group
            ),
            len(items),
        )
        selected = items[:limit]
        logger.info("分组 [%s] 保留 %d/%d 条候选", group, len(selected), len(items))
        final_results.extend(selected)

    for leftovers in grouped_results.values():
        final_results.extend(leftovers)

    final_results.sort(key=lambda item: item["ranking_score"], reverse=True)
    logger.info("共找到 %d 条新闻（已过滤低质量来源并按分组限额排序）", len(final_results))
    return final_results


def _ranking_score(item: dict[str, Any]) -> float:
    return (
        int(item.get("tier", "3")) * 10
        + GROUP_PRIORITY.get(item.get("group", "general"), 10)
        + item.get("freshness_score", 0.0) * 8
        + item.get("score", 0.0) * 5
    )


def _freshness_score(value: str) -> float:
    if not value:
        return 0.0
    normalized = value.replace("Z", "+00:00")
    try:
        published_at = datetime.fromisoformat(normalized)
    except ValueError:
        return 0.0
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max((datetime.now(timezone.utc) - published_at).total_seconds() / 3600, 0)
    if age_hours <= 6:
        return 1.0
    if age_hours <= 12:
        return 0.7
    if age_hours <= 24:
        return 0.35
    return 0.1
