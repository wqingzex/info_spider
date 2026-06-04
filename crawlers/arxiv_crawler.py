"""arXiv 论文爬取器 - 使用 RSS 订阅而非 API，规避 GH Actions IP 封锁"""
import time
import logging
from datetime import datetime, timedelta, timezone

import feedparser

from .http_client import build_client

logger = logging.getLogger(__name__)

# arXiv RSS 按分类，每个 feed 含最新约 2000 条
RSS_BASE = "https://rss.arxiv.org/rss/{cats}"

_RELEVANCE_KEYWORDS = [
    "vla", "vision language action", "embodied", "humanoid robot",
    "manipulation policy", "diffusion policy", "imitation learning",
    "sim-to-real", "sim2real", "dexterous", "robot learning",
    "lerobot", "foundation model robot", "world model robot",
    "reinforcement learning robot", "rl robot",
]


def _is_relevant(title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()
    return any(kw in text for kw in _RELEVANCE_KEYWORDS)


class ArxivCrawler:
    def __init__(self, config: dict, http_config: dict):
        self.config = config
        self.timeout = http_config.get("timeout", 30)
        self.delay = http_config.get("delay_between_requests", 2)
        self.headers = http_config.get("headers", {})

    def crawl(self) -> list[dict]:
        results = []
        seen_ids: set[str] = set()

        days_back = self.config.get("days_back", 3)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        categories = self.config.get("categories", ["cs.RO"])
        max_results = self.config.get("max_results", 50)

        # 合并分类订阅一个 RSS（arXiv 支持 cat1+cat2 语法）
        cats = "+".join(categories)
        url = RSS_BASE.format(cats=cats)
        logger.info(f"arXiv RSS: {url}")

        try:
            with build_client(self.timeout, self.headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
            time.sleep(self.delay)

            feed = feedparser.parse(resp.text)
            for entry in feed.entries:
                # arXiv RSS id 格式: https://arxiv.org/abs/XXXX.XXXXX
                arxiv_id = entry.get("id", "").split("/abs/")[-1]
                if not arxiv_id or arxiv_id in seen_ids:
                    continue

                # 发布日期
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    try:
                        published = datetime(*pub[:6], tzinfo=timezone.utc)
                    except Exception:
                        continue
                    if published < cutoff:
                        continue
                else:
                    continue

                title = entry.get("title", "").strip().replace("\n", " ")
                raw_summary = entry.get("summary", "").strip().replace("\n", " ")
                # 去掉 arXiv RSS 的 "arXiv:XXXX Announce Type: new Abstract: " 前缀
                import re as _re
                raw_summary = _re.sub(r"arXiv:\S+\s+Announce Type:\s+\w+\s+Abstract:\s*", "", raw_summary).strip()
                summary = raw_summary[:500]
                link = entry.get("link", f"https://arxiv.org/abs/{arxiv_id}")

                # 关键词相关性过滤
                if not _is_relevant(title, summary):
                    continue

                # 分类标签
                tags = [t.get("term", "") for t in entry.get("tags", [])]

                seen_ids.add(arxiv_id)
                results.append({
                    "id": f"arxiv:{arxiv_id}",
                    "title": title,
                    "url": link,
                    "summary": summary,
                    "authors": [a.get("name", "") for a in entry.get("authors", [])][:5],
                    "categories": tags,
                    "published": published.isoformat(),
                    "source": "arXiv",
                    "source_category": "paper",
                })

                if len(results) >= max_results:
                    break

        except Exception as e:
            logger.error(f"arXiv RSS 爬取失败: {e}")

        logger.info(f"arXiv: 获取 {len(results)} 篇论文")
        return results
