"""GitHub 搜索爬虫 - 查找 VLA/具身智能相关仓库"""
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from .http_client import build_client

logger = logging.getLogger(__name__)


class GithubCrawler:
    SEARCH_URL = "https://api.github.com/search/repositories"

    def __init__(self, config: dict, http_config: dict):
        self.config = config
        self.timeout = http_config.get("timeout", 20)
        self.delay = http_config.get("delay_between_requests", 1.5)
        self.token = os.environ.get("GITHUB_TOKEN", "")

    def _build_headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "VLASpider/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def crawl(self, days_back: int = 7) -> list[dict]:
        results = []
        seen_ids = set()

        queries = self.config.get("queries", [])
        language = self.config.get("language", "")
        sort = self.config.get("sort", "updated")
        max_per_query = self.config.get("max_per_query", 5)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        for query in queries:
            full_query = f"{query} pushed:>{cutoff_str}"
            if language:
                full_query += f" language:{language}"

            params = {
                "q": full_query,
                "sort": sort,
                "order": "desc",
                "per_page": max_per_query,
            }

            try:
                logger.info(f"GitHub 搜索: {query[:40]}...")
                with build_client(self.timeout, self._build_headers()) as client:
                    resp = client.get(self.SEARCH_URL, params=params)
                    if resp.status_code == 403:
                        logger.warning("GitHub API 速率限制，跳过")
                        break
                    resp.raise_for_status()
                    data = resp.json()

                time.sleep(self.delay)

                for repo in data.get("items", []):
                    repo_id = str(repo.get("id", ""))
                    if repo_id in seen_ids:
                        continue
                    seen_ids.add(repo_id)

                    updated = repo.get("updated_at", "")
                    results.append({
                        "id": f"github:{repo_id}",
                        "title": repo.get("full_name", ""),
                        "url": repo.get("html_url", ""),
                        "summary": repo.get("description", "") or "",
                        "authors": [repo.get("owner", {}).get("login", "")],
                        "published": updated,
                        "stars": repo.get("stargazers_count", 0),
                        "source": "GitHub",
                        "source_category": "github",
                    })

            except Exception as e:
                logger.warning(f"GitHub 搜索失败 ({query[:30]}): {e}")

        logger.info(f"GitHub: 获取 {len(results)} 个仓库")
        return results
