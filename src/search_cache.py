"""
搜索结果缓存模块 - 按关键词类型设置不同 TTL
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 缓存存储目录
CACHE_DIR = Path("output/cache/search")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 各类型关键词的 TTL 设置（单位：秒）
DEFAULT_TTL = {
    "injury": 4 * 3600,       # 伤病更新：4小时
    "match_result": 6 * 3600, # 赛果：6小时
    "match_preview": 6 * 3600, # 比赛预览：6小时
    "transfer": 12 * 3600,     # 转会：12小时
    "press": 8 * 3600,        # 发布会：8小时
    "default": 6 * 3600,      # 默认：6小时
}


def _keyword_ttl(keyword: str) -> int:
    """根据关键词判断缓存 TTL"""
    kw = keyword.lower()
    if any(x in kw for x in ["injury", "fitness", "fitness", "timber", "odegaard", "saka", "calle"]):
        return DEFAULT_TTL["injury"]
    if any(x in kw for x in ["result", "score", " win ", " lose ", " draw ", " beat ", " victory", " defeat"]):
        return DEFAULT_TTL["match_result"]
    if any(x in kw for x in ["preview", "lineup", "team news", "starting", " XI "]):
        return DEFAULT_TTL["match_preview"]
    if any(x in kw for x in ["transfer", "sign", "bid", "offer", "contract", "signing"]):
        return DEFAULT_TTL["transfer"]
    if any(x in kw for x in ["press conference", "arteta", "presser"]):
        return DEFAULT_TTL["press"]
    return DEFAULT_TTL["default"]


def _cache_key(api_key: str, keyword: str, max_results: int, include_domains: list[str] | None) -> str:
    """生成缓存文件名的 hash key"""
    domains_str = ",".join(sorted(include_domains or []))
    data = f"{api_key}:{keyword}:{max_results}:{domains_str}"
    return hashlib.sha256(data.encode()).hexdigest()[:20]


def _read_cache(key: str) -> dict[str, Any] | None:
    """读取缓存，如果过期则返回 None"""
    cache_file = CACHE_DIR / f"{key}.json"
    if not cache_file.exists():
        return None

    try:
        entry = json.loads(cache_file.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(entry["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        ttl = entry["ttl"]

        if age > ttl:
            cache_file.unlink(missing_ok=True)
            return None

        return entry["data"]
    except (json.JSONDecodeError, KeyError, ValueError):
        cache_file.unlink(missing_ok=True)
        return None


def _write_cache(key: str, data: dict[str, Any], ttl: int) -> None:
    """写入缓存文件"""
    entry = {
        "data": data,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "ttl": ttl,
    }
    try:
        (CACHE_DIR / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("缓存写入失败: %s", key)


def cached_tavily_search(
    api_key: str,
    keyword: str,
    max_results: int,
    include_domains: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    带缓存的 Tavily 搜索
    - 优先读缓存，命中则直接返回
    - 未命中则调用 API，结果写入缓存
    """
    key = _cache_key(api_key, keyword, max_results, include_domains)
    ttl = _keyword_ttl(keyword)

    # 尝试读取缓存
    cached = _read_cache(key)
    if cached is not None:
        logger.info(f"🔵 缓存命中 [{keyword[:40]}] (TTL={ttl//3600}h)")
        return cached

    # 缓存未命中，调用原始搜索（这里假设调用方会处理异常）
    return None


def cleanup_expired_cache() -> int:
    """
    清理所有过期的缓存文件
    返回清理的文件数量
    """
    count = 0
    if not CACHE_DIR.exists():
        return 0

    for cache_file in CACHE_DIR.glob("*.json"):
        try:
            entry = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(entry["cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()
            ttl = entry.get("ttl", 0)

            if age > ttl:
                cache_file.unlink(missing_ok=True)
                count += 1
        except (json.JSONDecodeError, KeyError, ValueError):
            cache_file.unlink(missing_ok=True)
            count += 1

    if count > 0:
        logger.info(f"缓存清理: 删除 {count} 个过期文件")
    return count
