"""RSS/Atom Feed 爬取器 - 支持直接 RSS 和 RSSHub"""
import os
import time
import logging
from datetime import datetime, timedelta, timezone
import feedparser

from .http_client import build_client

logger = logging.getLogger(__name__)


def _parse_entry_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _match_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


class RssCrawler:
    def __init__(self, config: dict, http_config: dict):
        self.feeds = config.get("feeds", [])
        self.timeout = http_config.get("timeout", 20)
        self.delay = http_config.get("delay_between_requests", 1.5)
        self.headers = http_config.get("headers", {})
        self.rsshub_url = os.environ.get("RSSHUB_URL", "").rstrip("/")

    def _resolve_url(self, url: str) -> str | None:
        if "{RSSHUB_URL}" in url:
            if not self.rsshub_url:
                return None
            return url.replace("{RSSHUB_URL}", self.rsshub_url)
        return url

    def crawl(self, days_back: int = 2) -> list[dict]:
        results = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        for feed_cfg in self.feeds:
            name = feed_cfg.get("name", "unknown")
            raw_url = feed_cfg.get("url", "")
            keywords = feed_cfg.get("keywords", [])
            category = feed_cfg.get("category", "unknown")
            is_rsshub = feed_cfg.get("rsshub", False)

            url = self._resolve_url(raw_url)
            if url is None:
                logger.debug(f"跳过 {name}（未配置 RSSHUB_URL）")
                continue

            try:
                logger.info(f"RSS 爬取: {name}")
                with build_client(self.timeout, self.headers) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    content = resp.text
                time.sleep(self.delay)

                feed = feedparser.parse(content)
                count = 0

                for entry in feed.entries:
                    pub_date = _parse_entry_date(entry)
                    if pub_date and pub_date < cutoff:
                        continue

                    title = getattr(entry, "title", "").strip()
                    link = getattr(entry, "link", "")
                    summary = getattr(entry, "summary", "").strip()[:300]

                    if not title or not link:
                        continue

                    combined_text = f"{title} {summary}"
                    if not _match_keywords(combined_text, keywords):
                        continue

                    results.append({
                        "id": f"rss:{link}",
                        "title": title,
                        "url": link,
                        "summary": summary,
                        "authors": [],
                        "published": pub_date.isoformat() if pub_date else "",
                        "source": name,
                        "source_category": category,
                    })
                    count += 1

                logger.info(f"  {name}: {count} 条")

            except Exception as e:
                logger.warning(f"RSS {name} 失败: {e}")

        logger.info(f"RSS 总计: {len(results)} 条")
        return results
