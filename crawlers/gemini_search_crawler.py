"""Gemini Search 爬虫 - 使用 Gemini 2.0 内置 Google Search grounding
无需 Serper.dev，仅需 GEMINI_API_KEY（免费）
"""
import os
import re
import time
import logging
from datetime import datetime, timezone

# google-genai 用 httpx trust_env=True，会读取 ALL_PROXY(socks) 导致失败
# 清除 SOCKS 变量，保留 HTTP 代理
for _k in ("ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

logger = logging.getLogger(__name__)

# 每组搜索查询
SEARCH_TASKS = [
    # 国内媒体（绕过 WAF 直接通过 Gemini 搜）
    {
        "prompt": "搜索最新（最近3天）机器之心、量子位、新智元关于VLA、具身智能、人形机器人的文章，列出标题和链接",
        "name": "中文媒体-机器人",
        "category": "media_cn",
    },
    # 国内公司动态
    {
        "prompt": "搜索最新（最近7天）宇树科技、智元机器人、傅里叶智能、开普勒机器人、乐聚机器人的最新动态、新品发布或融资新闻，列出标题和链接",
        "name": "国内公司动态",
        "category": "company_cn",
    },
    # 国际公司动态
    {
        "prompt": "Search for the latest news (past 7 days) from Physical Intelligence, Figure AI, 1X Technologies, Agility Robotics, Apptronik about new robot releases or research. List titles and links.",
        "name": "国际公司动态",
        "category": "company_intl",
    },
    # VLA 综合新闻
    {
        "prompt": "Search for the latest news (past 3 days) about VLA (Vision Language Action) models, embodied AI, humanoid robots. List titles and links.",
        "name": "VLA综合",
        "category": "media_intl",
    },
    {
        "prompt": "Search for the latest papers or projects (past 7 days) on reinforcement learning for robot manipulation, sim-to-real transfer, dexterous manipulation, RLHF for robots. List titles and links.",
        "name": "RL机器人",
        "category": "paper",
    },
    # 微信公众号（通过 Google 索引部分公众号文章）
    {
        "prompt": "搜索最近3天微信公众号关于具身智能、人形机器人、VLA的文章（site:mp.weixin.qq.com），列出标题和链接",
        "name": "微信公众号",
        "category": "community_cn",
    },
]

_URL_RE = re.compile(r"https?://[^\s\)\]\"']+")


def _extract_grounding_urls(response) -> list[dict]:
    """从 Gemini grounding metadata 中提取搜索结果"""
    results = []
    try:
        meta = response.candidates[0].grounding_metadata
        if not meta:
            return results
        for chunk in (meta.grounding_chunks or []):
            web = getattr(chunk, "web", None)
            if web and web.uri:
                results.append({
                    "url": web.uri,
                    "title": getattr(web, "title", "") or "",
                })
    except Exception:
        pass
    return results


def _extract_urls_from_text(text: str) -> list[str]:
    """从文本中提取 URL（备用方案）"""
    return list(set(_URL_RE.findall(text)))


class GeminiSearchCrawler:
    def __init__(self, http_config: dict, extra_tasks: list | None = None):
        self.api_key = os.environ.get("GEMINI_API_KEY", "")
        self.delay = http_config.get("delay_between_requests", 1.5)
        self.extra_tasks = extra_tasks or []

    def crawl(self) -> list[dict]:
        if not self.api_key:
            logger.info("未配置 GEMINI_API_KEY，跳过 Gemini 搜索")
            return []

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.warning("google-genai 未安装")
            return []

        client = genai.Client(api_key=self.api_key)
        all_tasks = SEARCH_TASKS + self.extra_tasks
        results = []
        seen_urls: set[str] = set()

        # gemini-2.5-flash 免费层约 10 RPM，每次调用前等待 7 秒
        CALL_INTERVAL = 7

        for i, task in enumerate(all_tasks):
            name = task["name"]
            category = task["category"]
            prompt = task["prompt"]

            if i > 0:
                time.sleep(CALL_INTERVAL)

            try:
                logger.info(f"Gemini 搜索: {name}")
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.1,
                    ),
                )

                # 优先从 grounding metadata 提取（结构化，含标题）
                grounded = _extract_grounding_urls(resp)
                text = resp.text or ""

                if grounded:
                    for item in grounded:
                        url = item["url"]
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        results.append({
                            "id": f"gemini-search:{url}",
                            "title": item["title"] or url,
                            "url": url,
                            "summary": "",
                            "authors": [],
                            "published": datetime.now(timezone.utc).isoformat(),
                            "source": name,
                            "source_category": category,
                        })
                    logger.info(f"  {name}: {len(grounded)} 条（grounding）")
                else:
                    # 降级：从文本中提取 URL
                    urls = _extract_urls_from_text(text)
                    new = [u for u in urls if u not in seen_urls]
                    for url in new:
                        seen_urls.add(url)
                        results.append({
                            "id": f"gemini-search:{url}",
                            "title": url,
                            "url": url,
                            "summary": "",
                            "authors": [],
                            "published": datetime.now(timezone.utc).isoformat(),
                            "source": name,
                            "source_category": category,
                        })
                    logger.info(f"  {name}: {len(new)} 条（文本提取）")

            except Exception as e:
                err = str(e)
                if "429" in err:
                    import re
                    m = re.search(r"retryDelay.*?(\d+)s", err)
                    wait = int(m.group(1)) + 3 if m else 30
                    logger.warning(f"Gemini 搜索 {name} 速率限制，等 {wait}s 后重试...")
                    time.sleep(wait)
                    try:
                        resp = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                tools=[types.Tool(google_search=types.GoogleSearch())],
                                temperature=0.1,
                            ),
                        )
                        grounded = _extract_grounding_urls(resp)
                        for item in grounded:
                            url = item["url"]
                            if url not in seen_urls:
                                seen_urls.add(url)
                                results.append({
                                    "id": f"gemini-search:{url}",
                                    "title": item["title"] or url,
                                    "url": url,
                                    "summary": "",
                                    "authors": [],
                                    "published": datetime.now(timezone.utc).isoformat(),
                                    "source": name,
                                    "source_category": category,
                                })
                        logger.info(f"  {name}: {len(grounded)} 条（重试成功）")
                    except Exception as e2:
                        logger.warning(f"Gemini 搜索 {name} 重试失败: {e2}")
                else:
                    logger.warning(f"Gemini 搜索 {name} 失败: {e}")

        logger.info(f"Gemini 搜索总计: {len(results)} 条")
        return results
