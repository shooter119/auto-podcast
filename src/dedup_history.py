"""
去重历史记录管理器 - 自动过期 + 分层衰减

问题：history.json 无上限增长，同类新闻冷却期相同，导致：
- 热门新闻（赛果）反复被标记，后续报道被误杀
- 历史越积越多，最近的新闻反而被过滤

解决方案：
1. 每条记录带 TTL（按类型区分），自动过期
2. 历史记录有分层衰减（近期记录权重高，久远权重低）
3. 记录数量上限（LRU 淘汰）
4. 同事件多轮报道有独立冷却窗口
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("auto-podcast")

# 不同类型新闻的 TTL（秒）
NEWS_TTL = {
    "match_result": 72 * 3600,    # 赛果：72小时（3天）
    "transfer": 48 * 3600,          # 转会传闻：48小时
    "injury": 24 * 3600,           # 伤病更新：24小时
    "press": 36 * 3600,            # 发布会/采访：36小时
    "general": 18 * 3600,          # 一般新闻：18小时
}

# 历史记录上限（超出则 LRU 淘汰最老记录）
MAX_HISTORY_SIZE = 500

# 衰减系数：超过 TTL 的记录按此比例降低去重权重（0-1，1=不退化）
DECAY_RATE = 0.5

# 历史文件路径（由外部传入）
DEFAULT_HISTORY_FILE = Path("output/history.json")


def _classify_news(title: str, url: str) -> str:
    """根据标题和 URL 判断新闻类型"""
    text = (title + " " + url).lower()
    if any(x in text for x in ["result", "score", "beat", "win", "draw", "lose", "victory", "defeat", "game", "match report"]):
        return "match_result"
    if any(x in text for x in ["transfer", "sign", "bid", "offer", "contract", "signing"]):
        return "transfer"
    if any(x in text for x in ["injury", "fitness", "sick", "ill", "recovery", "hurt"]):
        return "injury"
    if any(x in text for x in ["press conference", "arteta", "presser", "interview", "exclusive"]):
        return "press"
    return "general"


def _fingerprint(article: dict[str, Any]) -> str:
    """生成新闻指纹，用于去重比较"""
    title = article.get("title", "")
    # 提取关键信息：去除比分、数字、常见词
    normalized = "".join(
        c for c in title.lower()
        if c.isalpha() or c.isspace()
    ).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _event_fingerprint(article: dict[str, Any]) -> str:
    """事件指纹：同一事件的不同报道应被视为同类（用于赛果去重）"""
    title = article.get("title", "")
    # 提取球队名（英文大写缩写）+ 比分模式
    import re
    # 找 "Arsenal 3-1" 这样的模式
    score_pattern = re.findall(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+\d[-\d]+\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', title)
    if score_pattern:
        teams = tuple(sorted(sum(score_pattern, ())))
        return hashlib.sha256((" ".join(teams)).encode()).hexdigest()[:16]

    # 降级：用主语+动词短语
    words = title.split()[:4]
    return hashlib.sha256((" ".join(words)).encode()).hexdigest()[:16]


class DedupHistory:
    """
    智能去重历史管理器
    - 自动过期（TTL）
    - 分层衰减（decay）
    - LRU 淘汰（MAX_HISTORY_SIZE）
    - 事件指纹（同一事件多次报道）
    """

    def __init__(self, history_file: Path | str = DEFAULT_HISTORY_FILE):
        self.history_file = Path(history_file)
        self.entries: list[dict[str, Any]] = []
        self._load()

    def _load(self):
        """加载历史文件，过滤过期记录"""
        if not self.history_file.exists():
            self.entries = []
            return

        try:
            raw = json.loads(self.history_file.read_text(encoding="utf-8"))
            # 兼容旧格式（纯列表）
            if isinstance(raw, list):
                self.entries = raw
            else:
                self.entries = raw.get("entries", [])

            # 过滤过期记录
            now = datetime.now(timezone.utc)
            before = len(self.entries)
            self.entries = [e for e in self.entries if not self._is_expired(e, now)]
            after = len(self.entries)

            if before > after:
                logger.info(f"历史记录: 加载时清理 {before - after} 条过期记录，剩余 {after} 条")
        except Exception as e:
            logger.warning(f"历史记录加载失败: {e}，重置")
            self.entries = []

    def _is_expired(self, entry: dict[str, Any], now: datetime = None) -> bool:
        """判断记录是否已过期"""
        if now is None:
            now = datetime.now(timezone.utc)
        try:
            cached_at = datetime.fromisoformat(entry.get("cached_at", ""))
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            age = (now - cached_at).total_seconds()
            ttl = entry.get("ttl", NEWS_TTL["general"])
            return age > ttl
        except Exception:
            return True

    def _effective_weight(self, entry: dict[str, Any]) -> float:
        """
        计算记录的有效权重
        - 未过期：1.0
        - 过期但未超过2倍TTL：DECAY_RATE
        - 超过2倍TTL：淘汰或权重趋近0
        """
        if not self._is_expired(entry):
            return 1.0
        try:
            now = datetime.now(timezone.utc)
            cached_at = datetime.fromisoformat(entry.get("cached_at", ""))
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            age = (now - cached_at).total_seconds()
            ttl = entry.get("ttl", NEWS_TTL["general"])
            if age > 2 * ttl:
                return 0.0  # 超过2倍TTL，权重归零
            return DECAY_RATE * (1 - (age - ttl) / ttl)
        except Exception:
            return 0.0

    def add(self, article: dict[str, Any]) -> None:
        """
        添加一条新闻到历史记录
        article 应包含: title, url, content 等
        """
        news_type = _classify_news(article.get("title", ""), article.get("url", ""))
        ttl = NEWS_TTL.get(news_type, NEWS_TTL["general"])

        entry = {
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "ttl": ttl,
            "news_type": news_type,
            "fingerprint": _fingerprint(article),
            "event_fp": _event_fingerprint(article),
        }
        self.entries.append(entry)

        # LRU 淘汰：超出上限则删除最老记录
        if len(self.entries) > MAX_HISTORY_SIZE:
            # 按 cached_at 排序，删除最老的
            self.entries.sort(key=lambda e: e.get("cached_at", ""))
            removed = self.entries.pop(0)
            logger.info(f"历史记录 LRU 淘汰: {removed.get('title', '')[:40]}")

    def is_duplicate(self, article: dict[str, Any]) -> tuple[bool, str]:
        """
        判断新闻是否重复
        返回 (是否重复, 原因)
        重复原因: "fingerprint" | "event" | "url" | ""（不重复）
        """
        fp = _fingerprint(article)
        event_fp = _event_fingerprint(article)
        url = article.get("url", "")

        for entry in reversed(self.entries):  # 最近的优先
            weight = self._effective_weight(entry)
            if weight <= 0:
                continue

            # URL 精确匹配（最强信号）
            if url and entry.get("url", "") == url:
                return True, "url"

            # 事件指纹匹配（同类事件）
            if entry.get("event_fp") == event_fp and event_fp != "0" * 16:
                return True, "event"

            # 内容指纹匹配（标题近似）
            if entry.get("fingerprint") == fp and fp != "0" * 16:
                return True, "fingerprint"

        return False, ""

    def save(self):
        """保存历史到文件"""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        # 清理过期记录后再保存
        now = datetime.now(timezone.utc)
        self.entries = [e for e in self.entries if not self._is_expired(e, now)]
        data = {"entries": self.entries, "updated_at": datetime.now(timezone.utc).isoformat()}
        self.history_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"历史记录已保存: {len(self.entries)} 条")

    def stats(self) -> dict[str, Any]:
        """返回当前统计信息"""
        now = datetime.now(timezone.utc)
        active = sum(1 for e in self.entries if not self._is_expired(e, now))
        expired = len(self.entries) - active
        type_counts = {}
        for e in self.entries:
            t = e.get("news_type", "general")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "total": len(self.entries),
            "active": active,
            "expired": expired,
            "by_type": type_counts,
            "max_size": MAX_HISTORY_SIZE,
        }
