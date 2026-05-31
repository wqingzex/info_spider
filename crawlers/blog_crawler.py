"""公司官网博客爬虫 - 适配无 RSS 的网站"""
import time
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from .http_client import build_client

logger = logging.getLogger(__name__)


def _extract_text(el) -> str:
    return el.get_text(separator=" ", strip=True) if el else ""


def _normalize_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(base_url, href)


class BlogCrawler:
    def __init__(self, config: list, http_config: dict):
        self.sites = config
        self.timeout = http_config.get("timeout", 20)
        self.delay = http_config.get("delay_between_requests", 1.5)
        self.headers = http_config.get("headers", {})

    def _fetch(self, url: str) -> str | None:
        try:
            with build_client(self.timeout, self.headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception as e:
            logger.warning(f"请求失败 {url}: {e}")
            return None

    def _extract_articles(self, html: str, site: dict) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        base_url = site["url"]
        articles = []

        # 尝试配置的选择器
        article_selector = site.get("article_selector", "article")
        title_selector = site.get("title_selector", "h1, h2, h3")
        link_selector = site.get("link_selector", "a")

        containers = soup.select(article_selector)
        if not containers:
            # 降级：直接从整个页面提取链接
            containers = [soup]

        seen_urls = set()
        for container in containers[:20]:
            # 查找标题
            title_el = container.select_one(title_selector)
            title = _extract_text(title_el)
            if not title or len(title) < 5:
                continue

            # 查找链接
            link_el = container.select_one(link_selector)
            href = link_el.get("href", "") if link_el else ""
            url = _normalize_url(href, base_url)
            if not url or url in seen_urls:
                continue

            # 过滤：链接必须在同域或是子路径
            base_domain = urlparse(base_url).netloc
            link_domain = urlparse(url).netloc
            if link_domain and link_domain != base_domain:
                continue

            seen_urls.add(url)
            articles.append({
                "id": f"blog:{url}",
                "title": title[:200],
                "url": url,
                "summary": "",
                "authors": [],
                "published": datetime.now(timezone.utc).isoformat(),
                "source": site.get("name", "unknown"),
                "source_category": site.get("category", "company"),
            })

        return articles

    def crawl(self) -> list[dict]:
        results = []

        for site in self.sites:
            name = site.get("name", "unknown")
            url = site.get("url", "")
            if not url:
                continue

            logger.info(f"博客爬取: {name}")
            html = self._fetch(url)
            if not html:
                continue

            articles = self._extract_articles(html, site)
            logger.info(f"  {name}: {len(articles)} 篇")
            results.extend(articles)
            time.sleep(self.delay)

        logger.info(f"博客总计: {len(results)} 条")
        return results
