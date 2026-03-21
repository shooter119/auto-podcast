from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests
from readability import Document
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
MAX_CONTENT_LENGTH = 3000
MIN_CONTENT_LENGTH = 200
MAX_WORKERS = 5


def _extract_text_from_html(html: str) -> str:
    from lxml.html import fromstring
    from lxml.html.clean import Cleaner

    cleaner = Cleaner(
        scripts=True, javascript=True, comments=True,
        style=True, links=False, meta=True, page_structure=False,
        processing_instructions=True, embedded=True, frames=True,
        forms=True, annoying_tags=True, remove_unknown_tags=True,
    )
    doc = fromstring(html)
    doc = cleaner.clean_html(doc)
    return doc.text_content().strip()


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    reraise=True,
)
def _fetch_url(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def scrape_article(url: str) -> Optional[str]:
    try:
        html = _fetch_url(url)
        doc = Document(html)
        summary_html = doc.summary()
        text = _extract_text_from_html(summary_html)
        if len(text) > MAX_CONTENT_LENGTH:
            text = text[:MAX_CONTENT_LENGTH] + "..."
        return text if len(text) > 100 else None
    except Exception:
        logger.exception("抓取失败: %s", url)
        return None


def enrich_articles(results: list[dict[str, str]]) -> list[dict[str, str]]:
    """Enrich articles that have insufficient content from Tavily."""
    articles = []
    needs_scraping = []

    for item in results:
        content = item.get("content", "")
        if len(content) >= MIN_CONTENT_LENGTH:
            articles.append(item)
        else:
            needs_scraping.append(item)

    if not needs_scraping:
        logger.info("全部 %d 篇文章内容充足，无需额外抓取", len(articles))
        return articles

    logger.info("%d 篇文章内容不足，尝试补充抓取", len(needs_scraping))

    def _process(item):
        logger.info("补充抓取: %s", item["url"])
        scraped = scrape_article(item["url"])
        return {
            "title": item["title"],
            "url": item["url"],
            "tier": item.get("tier", "3"),
            "content": scraped if scraped else item.get("content", ""),
        }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_process, item): item for item in needs_scraping}
        for future in as_completed(futures):
            try:
                articles.append(future.result())
            except Exception:
                item = futures[future]
                logger.exception("补充抓取失败: %s", item["url"])
                articles.append(item)

    articles.sort(key=lambda x: int(x.get("tier", "3")), reverse=True)
    logger.info("共 %d 篇文章准备就绪", len(articles))
    return articles
