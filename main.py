from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.run_state import create_run_context, load_state, mark_step, save_state

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("auto-podcast")

PROJECT_DIR = Path(__file__).parent
DEFAULT_CONFIG = PROJECT_DIR / "config.yaml"
OUTPUT_DIR = PROJECT_DIR / "output"
STEPS = ["search", "scrape", "filter", "dedup", "script", "tts", "upload", "rss"]


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def parse_args():
    parser = argparse.ArgumentParser(description="阿森纳每日播客自动生成")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只生成脚本，不合成音频和上传")
    parser.add_argument("--step", choices=STEPS, default=None, help="从指定步骤开始执行（断点恢复）")
    parser.add_argument("--run-id", type=str, default=None, help="指定本次运行ID，便于重试复用同一运行目录")
    return parser.parse_args()


def should_run(step: str, start_step: str | None) -> bool:
    if start_step is None:
        return True
    return STEPS.index(step) >= STEPS.index(start_step)


def main():
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    context = create_run_context(OUTPUT_DIR, args.run_id)
    setup_logging(context.log_path)

    # 启动时清理过期缓存（后台异步，不阻塞主流程）
    import threading
    def _cleanup_cache():
        try:
            from src.searcher import _keyword_ttl
            import hashlib, json, logging
            from pathlib import Path
            from datetime import datetime, timezone
            cache_dir = Path("output/cache/search")
            if cache_dir.exists():
                count = 0
                for f in cache_dir.glob("*.json"):
                    try:
                        entry = json.loads(f.read_text(encoding="utf-8"))
                        cached_at = datetime.fromisoformat(entry["cached_at"])
                        if cached_at.tzinfo is None:
                            cached_at = cached_at.replace(tzinfo=timezone.utc)
                        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
                        if age > entry.get("ttl", 0):
                            f.unlink(missing_ok=True)
                            count += 1
                    except Exception:
                        f.unlink(missing_ok=True)
                        count += 1
                if count > 0:
                    logging.getLogger("auto-podcast").info(f"缓存清理: 删除 {count} 个过期文件")
        except Exception:
            pass
    threading.Thread(target=_cleanup_cache, daemon=True).start()

    logger.info("=== 北伦敦24小时 · 播客生成开始 ===")
    logger.info("run_id=%s", context.run_id)

    from src.config_loader import load_config

    config = load_config(args.config)
    state = load_state(context)
    state["run_id"] = context.run_id
    state["started_at"] = state.get("started_at") or datetime.now().isoformat()
    save_state(context, state)

    today = datetime.now().strftime("%Y年%m月%d日")
    timestamp_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_tag = datetime.now().strftime("%Y%m%d")

    results = None
    articles = None
    script = None
    audio_path = None
    audio_url = state.get("artifacts", {}).get("audio_url")

    try:
        if should_run("search", args.step):
            logger.info("步骤1/8: 搜索新闻...")
            from src.searcher import search_news

            results = search_news(config)
            if not results:
                mark_step(context, state, "search", "empty", detail="未找到任何新闻")
                logger.warning("未找到任何新闻，退出")
                return
            _write_json(context.articles_path, results)
            mark_step(
                context,
                state,
                "search",
                "completed",
                artifacts={"search_results": str(context.articles_path)},
                metrics={"search_results_count": len(results)},
            )
        else:
            logger.info("跳过步骤: search")
            results = _read_json(Path(state.get("artifacts", {}).get("search_results", context.articles_path)))

        if should_run("scrape", args.step) and results:
            logger.info("步骤2/8: 补充抓取文章内容...")
            from src.scraper import enrich_articles

            articles = enrich_articles(results)
            if not articles:
                mark_step(context, state, "scrape", "empty", detail="未能获取任何文章内容")
                logger.warning("未能获取任何文章内容，退出")
                return
            _write_json(context.articles_path, articles)
            mark_step(
                context,
                state,
                "scrape",
                "completed",
                artifacts={"scraped_articles": str(context.articles_path)},
                metrics={"scraped_articles_count": len(articles)},
            )
        elif not should_run("scrape", args.step):
            logger.info("跳过步骤: scrape")
            articles = _read_json(Path(state.get("artifacts", {}).get("scraped_articles", context.articles_path)))

        if should_run("filter", args.step) and articles:
            logger.info("步骤3/8: 足球相关性过滤...")
            from src.relevance import filter_relevant

            articles = filter_relevant(articles, config)
            if not articles:
                mark_step(context, state, "filter", "empty", detail="过滤后无足球相关新闻")
                logger.warning("过滤后无足球相关新闻，退出")
                return
            _write_json(context.articles_path, articles)
            mark_step(
                context,
                state,
                "filter",
                "completed",
                artifacts={"filtered_articles": str(context.articles_path)},
                metrics={"filtered_articles_count": len(articles)},
            )
        elif not should_run("filter", args.step):
            logger.info("跳过步骤: filter")
            articles = _read_json(Path(state.get("artifacts", {}).get("filtered_articles", context.articles_path)))

        if should_run("dedup", args.step) and articles:
            logger.info("步骤4/8: 新闻去重...")
            from src.dedup import deduplicate

            articles = deduplicate(articles, config)
            if not articles:
                mark_step(context, state, "dedup", "empty", detail="去重后无新闻")
                logger.warning("去重后无新闻，退出")
                return
            _write_json(context.articles_path, articles)
            mark_step(
                context,
                state,
                "dedup",
                "completed",
                artifacts={"deduped_articles": str(context.articles_path)},
                metrics={"deduped_articles_count": len(articles)},
            )
        elif not should_run("dedup", args.step):
            logger.info("跳过步骤: dedup")
            articles = _read_json(Path(state.get("artifacts", {}).get("deduped_articles", context.articles_path)))

        if should_run("script", args.step) and articles:
            logger.info("步骤5/8: 生成播客脚本...")
            from src.script_generator import generate_script

            script = generate_script(articles, config)
            context.script_path.write_text(script, encoding="utf-8")
            mark_step(
                context,
                state,
                "script",
                "completed",
                artifacts={"script": str(context.script_path), "articles": str(context.articles_path)},
                metrics={"script_length": len(script)},
            )
            logger.info("脚本已保存: %s", context.script_path)
        else:
            if context.script_path.exists():
                script = context.script_path.read_text(encoding="utf-8")
                logger.info("从本地加载已有脚本: %s", context.script_path)

        if args.dry_run:
            mark_step(context, state, "dry_run", "completed", detail="仅生成脚本和中间结果")
            logger.info("=== dry-run模式，跳过音频合成和上传 ===")
            return

        if should_run("tts", args.step) and script:
            logger.info("步骤6/8: TTS合成音频...")
            from src.tts import generate_audio

            audio_path = generate_audio(script, config, output_path=context.audio_path)
            mark_step(
                context,
                state,
                "tts",
                "completed",
                artifacts={"audio": str(audio_path)},
                metrics={"audio_size_bytes": audio_path.stat().st_size},
            )
        else:
            if context.audio_path.exists():
                audio_path = context.audio_path
                logger.info("使用已有音频: %s", audio_path)

        if not audio_path or not audio_path.exists():
            logger.error("无音频文件可上传，退出")
            return

        if should_run("upload", args.step):
            logger.info("步骤7/8: 上传音频到R2...")
            from src.uploader import upload_file

            audio_key = state.get("artifacts", {}).get("audio_key") or f"episodes/{date_tag}/podcast_{context.run_id}.mp3"
            try:
                audio_url = upload_file(audio_path, audio_key, config)
                mark_step(
                    context,
                    state,
                    "upload",
                    "completed",
                    artifacts={"audio": str(audio_path), "audio_url": audio_url, "audio_key": audio_key},
                )
            except Exception:
                logger.exception("上传失败，音频已保存在本地: %s", audio_path)
                logger.info("可使用 --run-id %s --step upload 重新上传", context.run_id)
                raise

        if should_run("rss", args.step) and audio_url:
            logger.info("步骤8/8: 更新RSS feed...")
            from src.rss import build_feed_xml
            from src.tts import get_audio_duration
            from src.uploader import upload_bytes

            audio_size = audio_path.stat().st_size
            audio_duration = get_audio_duration(audio_path)
            episode_id = f"{config['podcast']['title']}:{context.run_id}"
            episode_title = f"{config['podcast']['title']} - {today}"
            episode_desc = f"{today}的阿森纳新闻播报，共{len(articles) if articles else '?'}条新闻。run_id={context.run_id}"

            feed_xml = build_feed_xml(
                episode_id,
                episode_title,
                episode_desc,
                audio_url,
                audio_size,
                audio_duration,
                config,
            )
            feed_url = upload_bytes(feed_xml, "feed.xml", config, content_type="application/rss+xml")
            mark_step(
                context,
                state,
                "rss",
                "completed",
                artifacts={"feed_url": feed_url},
                metrics={"audio_duration_seconds": audio_duration},
            )

        state["finished_at"] = datetime.now().isoformat()
        save_state(context, state)
        logger.info("=== 北伦敦24小时 · 播客生成完成 ===")
        if audio_url:
            logger.info("音频: %s", audio_url)
        logger.info("RSS: %s/feed.xml", config["r2"]["public_url"].rstrip("/"))

    except KeyboardInterrupt:
        mark_step(context, state, "run", "interrupted", detail="用户中断")
        logger.info("用户中断")
    except Exception:
        mark_step(context, state, "run", "failed", detail="播客生成过程中发生错误")
        logger.exception("播客生成过程中发生错误")
        sys.exit(1)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    main()
