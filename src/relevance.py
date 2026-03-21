from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ARSENAL_KEYWORDS = {
    "arsenal", "gunners", "arteta", "emirates", "saka", "odegaard", "rice",
    "阿森纳", "枪手", "阿尔特塔", "萨卡", "赖斯", "厄德高",
}
RIVAL_KEYWORDS = {
    "manchester city", "man city", "liverpool", "chelsea", "tottenham", "spurs",
    "manchester united", "newcastle", "aston villa", "曼城", "利物浦", "切尔西",
    "热刺", "曼联", "纽卡", "维拉",
}
FOOTBALL_CONTEXT = {
    "football", "soccer", "premier league", "champions league", "transfer", "injury",
    "match", "fixture", "goal", "assist", "manager", "lineup", "英超", "欧冠",
    "足球", "转会", "伤病", "比赛", "进球", "助攻", "阵容",
}
EXCLUDED_KEYWORDS = {
    "cricket", "rugby", "tennis", "golf", "boxing", "mma", "ufc", "nba", "nfl",
    "nhl", "mlb", "baseball", "basketball", "fpl", "fantasy premier league",
    "fantasy football", "women's football", "women's soccer", "wsl", "女足",
    "女子足球", "梦幻足球", "梦幻英超",
}
MATCH_KEYWORDS = {"result", "score", "preview", "lineup", "fixture", "赛后", "比分", "赛前", "首发", "阵容"}
TRANSFER_KEYWORDS = {"transfer", "sign", "loan", "bid", "fee", "deal", "转会", "签约", "租借", "报价"}
INJURY_KEYWORDS = {"injury", "fitness", "return", "doubt", "hamstring", "膝盖", "伤病", "缺阵", "复出"}


def filter_relevant(articles: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    dropped = 0

    for article in articles:
        score, bucket, reason = _classify_article(article, config)
        article["relevance_score"] = score
        article["relevance_bucket"] = bucket
        article["relevance_reason"] = reason

        if bucket == "drop":
            dropped += 1
            logger.info("过滤不相关内容 (%s, %.2f): %s", reason, score, article.get("title", "")[:80])
            continue

        article["news_type"] = _detect_news_type(article)
        filtered.append(article)

    filtered.sort(
        key=lambda item: (
            1 if item["relevance_bucket"] == "arsenal_core" else 0,
            1 if item.get("news_type") == "match" else 0,
            1 if item.get("news_type") == "injury" else 0,
            float(item.get("relevance_score", 0.0)),
            float(item.get("ranking_score", 0.0)),
        ),
        reverse=True,
    )

    logger.info("相关性过滤: %d -> %d 条（丢弃 %d 条不相关）", len(articles), len(filtered), dropped)
    return filtered


def _classify_article(article: dict[str, Any], config: dict[str, Any]) -> tuple[float, str, str]:
    text = " ".join(
        [
            article.get("title", ""),
            article.get("content", ""),
            article.get("summary", ""),
            article.get("group", ""),
        ]
    ).lower()

    excluded_hits = sum(1 for keyword in EXCLUDED_KEYWORDS if keyword in text)
    if excluded_hits:
        return 0.0, "drop", f"命中排除词 {excluded_hits} 个"

    football_hits = sum(1 for keyword in FOOTBALL_CONTEXT if keyword in text)
    arsenal_hits = sum(1 for keyword in ARSENAL_KEYWORDS if keyword in text)
    rival_hits = sum(1 for keyword in RIVAL_KEYWORDS if keyword in text)

    if arsenal_hits >= 1 and football_hits >= 1:
        score = 0.8 + min(arsenal_hits * 0.08, 0.15) + min(football_hits * 0.02, 0.05)
        return min(score, 0.99), "arsenal_core", f"阿森纳强相关（阿森纳词 {arsenal_hits}，足球词 {football_hits}）"

    if article.get("group") == "arsenal_core" and football_hits >= 1:
        return 0.76, "arsenal_core", "阿森纳核心检索命中"

    if rival_hits >= 1 and football_hits >= 1:
        score = 0.55 + min(rival_hits * 0.06, 0.12)
        return min(score, 0.75), "league_tail", f"争冠或竞争对手相关（对手词 {rival_hits}）"

    if article.get("group") in {"rivals", "league"} and football_hits >= 2:
        return 0.52, "league_tail", f"{article.get('group')} 分组且足球上下文充分"

    return 0.0, "drop", "足球相关性不足"


def _detect_news_type(article: dict[str, Any]) -> str:
    text = " ".join([article.get("title", ""), article.get("content", ""), article.get("summary", "")]).lower()
    if any(keyword in text for keyword in MATCH_KEYWORDS):
        return "match"
    if any(keyword in text for keyword in TRANSFER_KEYWORDS):
        return "transfer"
    if any(keyword in text for keyword in INJURY_KEYWORDS):
        return "injury"
    return "news"
