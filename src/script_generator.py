from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.news_utils import normalize_title

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "prompt.txt"
QA_BANNED_TERMS = {
    "nba", "nfl", "fpl", "女足", "wsl", "fantasy premier league", "fantasy football",
}


def generate_script(articles: list[dict[str, Any]], config: dict[str, Any]) -> str:
    # 球员名称标准化（英文/昵称 → 标准中文名）
    from src.arsenal_knowledge import normalize_articles
    articles = normalize_articles(articles)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    content_config = config.get("content", {})
    host_config = config.get("host", {})
    podcast_config = config.get("podcast", {})

    min_words = int(content_config.get("min_words", 3400))
    max_words = int(content_config.get("max_words", 4200))
    host_name = host_config.get("name", "主播")
    show_name = podcast_config.get("title", "北伦敦24小时")

    prompt = template.format(
        date=datetime.now().strftime("%Y年%m月%d日"),
        articles=_build_articles_text(articles, config),
        match_mode=_detect_match_mode(articles),
        min_words=min_words,
        max_words=max_words,
        wpm=int(content_config.get("words_per_minute", 280)),
        host_name=host_name,
        personality=host_config.get("personality", "你是一位足球播客主播。"),
        catchphrases="、".join(host_config.get("catchphrases", [])),
        show_name=show_name,
        team_ratio=int(float(content_config.get("team_ratio", 0.7)) * 100),
    )

    system_msg = (
        f"你是播客「{show_name}」的主播{host_name}。\n"
        f"{host_config.get('personality', '')}\n"
        "你只能基于提供的素材播报。禁止补充外部事实、禁止臆测、禁止编造引语。"
        "先讲事实，再讲球迷视角。阿森纳内容必须是绝对主线。"
    )

    retry_limit = int(content_config.get("qa_retry_limit", 1))
    qa_failures: list[str] = []

    for attempt in range(retry_limit + 1):
        script = _call_openclaw(system_msg, prompt, config)
        issues = _quality_check(script, articles, config)
        if not issues:
            logger.info("脚本生成完成，字数: %d", len(script))
            return script

        qa_failures.append("; ".join(issues))
        logger.warning("脚本质检未通过，第 %d 次生成发现问题: %s", attempt + 1, " | ".join(issues))
        prompt = _append_revision_note(prompt, issues)

    raise ValueError(f"脚本质检失败: {qa_failures[-1]}")


def _build_articles_text(articles: list[dict[str, Any]], config: dict[str, Any]) -> str:
    sections = {
        "主线新闻": _select_articles(articles, bucket="arsenal_core", limit=config["content"].get("main_feed_limit", 8)),
        "比赛相关": _select_articles(articles, bucket="arsenal_core", news_type="match", limit=config["content"].get("match_feed_limit", 4)),
        "转会动态": _select_articles(articles, bucket="arsenal_core", news_type="transfer", limit=config["content"].get("transfer_feed_limit", 3)),
        "联赛尾声": _select_articles(articles, bucket="league_tail", limit=config["content"].get("league_feed_limit", 5)),
    }

    parts: list[str] = []
    seen_urls: set[str] = set()
    for section_name, items in sections.items():
        unique_items = []
        for item in items:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            unique_items.append(item)
        if not unique_items:
            continue
        parts.append(f"=== {section_name} ===")
        for index, article in enumerate(unique_items, 1):
            parts.append(
                f"【{index}】[Tier{article.get('tier', '3')}][{article.get('news_type', 'news')}][{article.get('relevance_reason', '已筛选')}]\n"
                f"标题：{article.get('title', '')}\n"
                f"来源：{article.get('source_domain', '')}\n"
                f"链接：{article.get('url', '')}\n"
                f"摘要：{article.get('summary', '') or article.get('content', '')}\n"
                f"正文：{article.get('content', '')}\n"
            )
    return "\n".join(parts)


def _select_articles(
    articles: list[dict[str, Any]],
    *,
    bucket: str,
    limit: int,
    news_type: str | None = None,
) -> list[dict[str, Any]]:
    selected = [
        article for article in articles
        if article.get("relevance_bucket") == bucket and (news_type is None or article.get("news_type") == news_type)
    ]
    selected.sort(
        key=lambda item: (
            float(item.get("relevance_score", 0.0)),
            float(item.get("ranking_score", 0.0)),
            float(item.get("freshness_score", 0.0)),
        ),
        reverse=True,
    )
    return selected[: max(int(limit), 0)]


def _detect_match_mode(articles: list[dict[str, Any]]) -> str:
    match_count = sum(1 for article in articles if article.get("news_type") == "match")
    transfer_count = sum(1 for article in articles if article.get("news_type") == "transfer")
    injury_count = sum(1 for article in articles if article.get("news_type") == "injury")
    if match_count >= 3:
        return "赛比赛日报模式：重点讲清比赛事实、表现、数据和余波"
    if injury_count >= 2:
        return "阵容健康模式：重点处理伤病、缺阵与复出消息"
    if transfer_count >= 2:
        return "转会窗口模式：重点梳理报价、传闻与可信度"
    return "常规日更模式：重点聊俱乐部动态、备战和英超大盘"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=20),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)),
    reraise=True,
)
def _call_openclaw(system_msg: str, user_msg: str, config: dict[str, Any]) -> str:
    openclaw = config["openclaw"]
    gateway_url = openclaw["gateway_url"].rstrip("/")
    endpoint = f"{gateway_url}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    auth_token = openclaw.get("auth_token")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    agent_id = openclaw.get("agent_id")
    if agent_id:
        headers["x-openclaw-agent-id"] = agent_id

    payload = {
        "model": openclaw.get("model", "openclaw"),
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": float(openclaw.get("temperature", 0.5)),
        "user": openclaw.get("user", "auto-podcast"),
    }

    response = httpx.post(endpoint, headers=headers, json=payload, timeout=int(openclaw.get("timeout_seconds", 300)))
    response.raise_for_status()
    data = response.json()

    choices = data.get("choices", [])
    if not choices:
        raise ValueError("OpenClaw 返回为空")

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        parts = [block.get("text", "") for block in content if isinstance(block, dict)]
        content = "".join(parts)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenClaw 响应中未找到文本内容")

    logger.info("调用 OpenClaw 生成脚本成功 (model=%s, agent=%s)", payload["model"], agent_id or "default")
    return content.strip()


def _quality_check(script: str, articles: list[dict[str, Any]], config: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    content_config = config.get("content", {})
    min_words = int(content_config.get("min_words", 3400))
    max_words = int(content_config.get("max_words", 4200))
    team_ratio = float(content_config.get("team_ratio", 0.7))

    script_length = len(script)
    if script_length < int(min_words * 0.85):
        issues.append(f"字数偏少 {script_length}")
    if script_length > int(max_words * 1.1):
        issues.append(f"字数偏多 {script_length}")

    lowered = script.lower()
    for banned in QA_BANNED_TERMS:
        if banned in lowered:
            issues.append(f"出现禁词 {banned}")
            break

    if "北伦敦24小时" not in script and config.get("podcast", {}).get("title", "") not in script:
        issues.append("缺少节目名")
    if "各位枪迷" not in script and "今天" not in script:
        issues.append("开场感不足")
    if "明天" not in script and "下期" not in script and "收听" not in script:
        issues.append("收尾感不足")

    tail_markers = ["英超江湖", "尾声", "最后再说"]
    has_tail_marker = any(marker in script for marker in tail_markers)
    if not has_tail_marker:
        issues.append("缺少英超尾声段落")

    team_mentions = sum(script.count(word) for word in ["阿森纳", "枪手", "阿尔特塔", "萨卡"])
    league_mentions = sum(script.count(word) for word in ["曼城", "利物浦", "切尔西", "热刺", "英超"])
    if team_mentions <= 0 or team_mentions / max(team_mentions + league_mentions, 1) < team_ratio * 0.6:
        issues.append("阿森纳主线占比不足")

    allowed_names = _allowed_terms(articles)
    hallucinated_names = _find_unknown_proper_terms(script, allowed_names)
    if hallucinated_names:
        issues.append(f"疑似素材外实体: {', '.join(hallucinated_names[:4])}")

    return issues


def _allowed_terms(articles: list[dict[str, Any]]) -> set[str]:
    allowed = {"阿森纳", "英超", "欧冠", "热刺", "切尔西", "曼城", "利物浦"}
    for article in articles:
        normalized = normalize_title(article.get("title", ""))
        allowed.update(token for token in normalized.split() if len(token) >= 3)
    return allowed


def _find_unknown_proper_terms(script: str, allowed_terms: set[str]) -> list[str]:
    candidates = set(re.findall(r"\b[A-Z][A-Za-z\-\']{2,}\b", script))
    unknown: list[str] = []
    for term in candidates:
        lowered = term.lower()
        if lowered in allowed_terms:
            continue
        if re.fullmatch(r"\d+", term):
            continue
        unknown.append(term)
    return sorted(unknown)[:8]


def _append_revision_note(prompt: str, issues: list[str]) -> str:
    joined = "；".join(issues)
    return f"{prompt}\n\n补充修正要求：上一版存在这些问题：{joined}。请严格修正后重新输出完整纯文本脚本。"
