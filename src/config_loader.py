from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

REQUIRED_KEYS = [
    "tavily.api_key",
    "openclaw.gateway_url",
    "openclaw.model",
    "r2.account_id",
    "r2.access_key_id",
    "r2.secret_access_key",
    "r2.bucket",
    "r2.public_url",
]

ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        def _replacer(match):
            var_name = match.group(1)
            env_val = os.environ.get(var_name)
            if env_val is None:
                logger.warning("环境变量未设置: %s", var_name)
                return match.group(0)
            return env_val
        return ENV_VAR_PATTERN.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _get_nested(config: dict, key_path: str) -> Any:
    keys = key_path.split(".")
    val = config
    for k in keys:
        if not isinstance(val, dict) or k not in val:
            return None
        val = val[k]
    return val


def validate_config(config: dict[str, Any]) -> list[str]:
    errors = []
    for key_path in REQUIRED_KEYS:
        val = _get_nested(config, key_path)
        if val is None or (isinstance(val, str) and val.startswith("${")):
            errors.append(f"配置缺失或未解析: {key_path}")
    if not config.get("keywords"):
        errors.append("配置缺失: keywords (至少需要一个关键词)")
    if not isinstance(config.get("keywords"), dict):
        errors.append("配置缺失: keywords 需要为分组字典，例如 arsenal_core / rivals / league")
    return errors


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = _resolve_env_vars(config or {})
    config = _apply_defaults(config)

    errors = validate_config(config)
    if errors:
        for err in errors:
            logger.error(err)
        raise ValueError(f"配置校验失败，共 {len(errors)} 个错误")

    logger.info("配置加载成功")
    return config


def _apply_defaults(config: dict[str, Any]) -> dict[str, Any]:
    keywords = config.setdefault("keywords", {})
    for group_name, default_limit, default_final_limit in (
        ("arsenal_core", 8, 10),
        ("rivals", 6, 4),
        ("league", 5, 4),
    ):
        group_cfg = keywords.get(group_name, [])
        if isinstance(group_cfg, list):
            group_cfg = {"queries": group_cfg}
        if not isinstance(group_cfg, dict):
            group_cfg = {"queries": []}
        group_cfg.setdefault("queries", [])
        group_cfg.setdefault("max_results", default_limit)
        group_cfg.setdefault("final_limit", default_final_limit)
        group_cfg.setdefault("restrict_to_sources", group_name != "arsenal_core")
        keywords[group_name] = group_cfg

    content = config.setdefault("content", {})
    content.setdefault("target_duration_minutes", 13)
    content.setdefault("words_per_minute", 280)
    content.setdefault("min_words", 3400)
    content.setdefault("max_words", 4200)
    content.setdefault("team_ratio", 0.7)
    content.setdefault("tail_max_items", 5)
    content.setdefault("tail_max_minutes", 3)
    content.setdefault("main_feed_limit", 8)
    content.setdefault("match_feed_limit", 4)
    content.setdefault("transfer_feed_limit", 3)
    content.setdefault("league_feed_limit", content["tail_max_items"])
    content.setdefault("qa_retry_limit", 1)

    dedup = config.setdefault("dedup", {})
    dedup.setdefault("cooldown_match_hours", 48)
    dedup.setdefault("cooldown_transfer_hours", 36)
    dedup.setdefault("cooldown_news_hours", 18)
    dedup.setdefault("similarity_threshold", 0.86)
    dedup.setdefault("history_file", "output/history.json")
    dedup.setdefault("fallback_keep", 2)

    openclaw = config.setdefault("openclaw", {})
    openclaw.setdefault("timeout_seconds", 300)
    openclaw.setdefault("temperature", 0.5)
    openclaw.setdefault("agent_id", "main")
    openclaw.setdefault("user", "auto-podcast")

    tavily = config.setdefault("tavily", {})
    tavily.setdefault("max_results_per_keyword", 6)

    return config
