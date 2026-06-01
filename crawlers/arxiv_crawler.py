"""arXiv 论文爬取器 - 使用官方 Atom API"""
import time
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from .http_client import build_client

logger = logging.getLogger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"


class ArxivCrawler:
    BASE_URL = "http://export.arxiv.org/api/query"

    def __init__(self, config: dict, http_config: dict):
        self.config = config
        self.timeout = http_config.get("timeout", 20)
        self.delay = http_config.get("delay_between_requests", 1.5)
        self.headers = http_config.get("headers", {})

    def crawl(self) -> list[dict]:
        results = []
        seen_ids = set()

        days_back = self.config.get("days_back", 2)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        categories = self.config.get("categories", ["cs.RO"])
        keywords = self.config.get("keywords", [])
        max_results = self.config.get("max_results", 30)

        # 构建查询：分类 OR + 关键词 OR
        cat_query = " OR ".join(f"cat:{c}" for c in categories)
        if keywords:
            kw_query = " OR ".join(f'ti:"{k}" OR abs:"{k}"' for k in keywords[:6])
            query = f"({cat_query}) AND ({kw_query})"
        else:
            query = f"({cat_query})"

        params = {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": max_results,
            "start": 0,
        }

        retries = 3
        for attempt in range(retries):
            url = f"{self.BASE_URL}?{urlencode(params)}"
            if attempt == 0:
                logger.info(f"arXiv query: {url}")
            try:
                with build_client(self.timeout, self.headers) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                time.sleep(self.delay)
                break
            except Exception as e:
                wait = 10 * (2 ** attempt)
                logger.warning(f"arXiv 请求失败 (attempt {attempt+1}/{retries}): {e}, 等待 {wait}s")
                if attempt < retries - 1:
                    time.sleep(wait)
                else:
                    logger.error(f"arXiv 爬取失败，已重试 {retries} 次")
                    return results

            root = ET.fromstring(resp.text)
            entries = root.findall(f"{{{ATOM_NS}}}entry")

            for entry in entries:
                arxiv_id = entry.findtext(f"{{{ATOM_NS}}}id", "").split("/abs/")[-1]
                if arxiv_id in seen_ids:
                    continue

                published_str = entry.findtext(f"{{{ATOM_NS}}}published", "")
                try:
                    published = datetime.fromisoformat(
                        published_str.replace("Z", "+00:00")
                    )
                except Exception:
                    continue

                if published < cutoff:
                    continue

                title = entry.findtext(f"{{{ATOM_NS}}}title", "").strip().replace("\n", " ")
                summary = entry.findtext(f"{{{ATOM_NS}}}summary", "").strip().replace("\n", " ")[:500]
                authors = [
                    a.findtext(f"{{{ATOM_NS}}}name", "")
                    for a in entry.findall(f"{{{ATOM_NS}}}author")
                ]
                link = entry.findtext(f"{{{ATOM_NS}}}id", "").replace("/abs/", "/abs/")

                # 提取分类标签
                categories_found = [
                    tag.get("term", "")
                    for tag in entry.findall(f"{{{ATOM_NS}}}category")
                ]

                seen_ids.add(arxiv_id)
                results.append({
                    "id": f"arxiv:{arxiv_id}",
                    "title": title,
                    "url": link,
                    "summary": summary,
                    "authors": authors[:5],
                    "categories": categories_found,
                    "published": published.isoformat(),
                    "source": "arXiv",
                    "source_category": "paper",
                })

        except Exception as e:
            logger.error(f"arXiv 爬取失败: {e}")

        logger.info(f"arXiv: 获取 {len(results)} 篇论文")
        return results
