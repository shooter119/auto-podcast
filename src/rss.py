from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from feedgen.feed import FeedGenerator
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

FEED_FILENAME = "feed.xml"


def _init_feed(config: dict[str, Any]) -> FeedGenerator:
    podcast_config = config["podcast"]
    public_url = config["r2"]["public_url"].rstrip("/")

    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title(podcast_config["title"])
    fg.description(podcast_config["description"])
    fg.link(href=f"{public_url}/{FEED_FILENAME}", rel="self")
    fg.language(podcast_config.get("language", "zh-cn"))
    fg.podcast.itunes_author(podcast_config.get("author", "Arsenal Daily Podcast"))
    fg.podcast.itunes_category("Sports")
    fg.podcast.itunes_explicit("no")

    cover_url = f"{public_url}/cover.png"
    fg.image(url=cover_url, title=podcast_config["title"], link=f"{public_url}/{FEED_FILENAME}")
    fg.podcast.itunes_image(cover_url)

    return fg


def _fetch_existing_items(config: dict[str, Any]) -> list[ET.Element]:
    try:
        from src.uploader import _get_s3_client
        client = _get_s3_client(config)
        resp = client.get_object(Bucket=config["r2"]["bucket"], Key=FEED_FILENAME)
        existing_xml = resp["Body"].read()
        root = ET.fromstring(existing_xml)
        channel = root.find("channel")
        if channel is not None:
            items = channel.findall("item")
            logger.info("现有feed中有 %d 个episode", len(items))
            return items
    except ClientError:
        logger.info("未找到现有feed，创建新的")
    except Exception:
        logger.info("未找到现有feed，创建新的")
    return []


def _format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def build_feed_xml(
    episode_id: str,
    episode_title: str,
    episode_description: str,
    audio_url: str,
    audio_size: int,
    audio_duration: int,
    config: dict[str, Any],
) -> bytes:
    max_episodes = config["podcast"].get("max_episodes", 90)

    existing_items = _fetch_existing_items(config)

    fg = _init_feed(config)

    now = datetime.now(timezone.utc)
    fe = fg.add_entry()
    fe.id(episode_id)
    fe.title(episode_title)
    fe.description(episode_description)
    fe.published(now)
    fe.enclosure(audio_url, str(audio_size), "audio/mpeg")
    fe.podcast.itunes_duration(_format_duration(audio_duration))

    xml_bytes = fg.rss_str(pretty=True)

    if existing_items:
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        seen_ids = {_entry_id(root.find("channel/item"))} if root.find("channel/item") is not None else set()
        seen_ids.discard(None)
        for item in existing_items:
            item_id = _entry_id(item)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            channel.append(item)
            if len(channel.findall("item")) >= max_episodes:
                break
        xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=True).encode("utf-8")

    logger.info("RSS feed已更新")
    return xml_bytes


def _entry_id(item: ET.Element | None) -> str | None:
    if item is None:
        return None
    guid = item.findtext("guid")
    if guid:
        return guid
    enclosure = item.find("enclosure")
    if enclosure is not None:
        return enclosure.attrib.get("url")
    return item.findtext("link")
