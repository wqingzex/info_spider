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
        "category": "media_intl",
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
    """从 Gemini grounding metadata 中提取搜索结果，含文章标题"""
    results = []
    seen = set()
    try:
        meta = response.candidates[0].grounding_metadata
        if not meta:
            return results

        # 优先从 grounding_supports 获取渲染标题（更准确）
        support_titles: dict[str, str] = {}
        for support in (getattr(meta, "grounding_supports", None) or []):
            indices = getattr(support, "grounding_chunk_indices", []) or []
            segment = getattr(support, "segment", None)
            if segment and indices:
                text = getattr(segment, "text", "") or ""
                if text and len(text) > 10:
                    for idx in indices:
                        if idx not in support_titles:
                            support_titles[idx] = text[:120]

        for i, chunk in enumerate(meta.grounding_chunks or []):
            web = getattr(chunk, "web", None)
            if not (web and web.uri):
                continue
            uri = web.uri
            if uri in seen:
                continue
            seen.add(uri)

            # 标题优先级：web.title > support text > 空
            title = getattr(web, "title", "") or support_titles.get(i, "")
            results.append({"url": uri, "title": title.strip()})
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
        CALL_INTERVAL = 15

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
                    # 从 response text 提取标题（格式 [title](url) 或 **title**）
                    import re as _re
                    text_titles: dict[str, str] = {}
                    for m in _re.finditer(r'\[([^\]]{5,120})\]\((https?://[^\)]+)\)', text):
                        t, u = m.group(1).strip(), m.group(2).strip()
                        if u not in text_titles and not t.startswith("http"):
                            text_titles[u] = t

                    # 金融/无关域名黑名单
                    _BLOCKED_DOMAINS = {
                        "kucoin.com", "morningstar.com", "thestreet.com",
                        "investing.com", "finance.yahoo.com", "nasdaq.com",
                        "bloomberg.com", "reuters.com", "marketwatch.com",
                        "coinbase.com", "binance.com", "tradingview.com",
                        "youtube.com",  # 视频不适合文本摘要
                    }

                    added = 0
                    for item in grounded:
                        url = item["url"]
                        if url in seen_urls:
                            continue
                        # 域名黑名单过滤
                        from urllib.parse import urlparse as _urlparse
                        domain = _urlparse(url).netloc.lstrip("www.")
                        if any(domain == b or domain.endswith("." + b) for b in _BLOCKED_DOMAINS):
                            continue
                        seen_urls.add(url)
                        # 优先用文本里提取的标题，其次用 grounding 标题，再次用域名
                        title = (text_titles.get(url) or item["title"] or "").strip()
                        if not title or "." in title.split("/")[-1][:6]:
                            # 标题像域名，用响应文本第一个相关句子
                            title = item["title"] or url
                        results.append({
                            "id": f"gemini-search:{url}",
                            "title": title,
                            "url": url,
                            "summary": "",
                            "authors": [],
                            "published": datetime.now(timezone.utc).isoformat(),
                            "source": name,
                            "source_category": category,
                        })
                        added += 1
                    logger.info(f"  {name}: {added} 条（grounding）")
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
                elif "503" in err or "UNAVAILABLE" in err:
                    logger.warning(f"Gemini 搜索 {name} 503 过载，等 30s 重试...")
                    time.sleep(30)
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
                        text = resp.text or ""
                        import re as _re2
                        text_titles2 = {u: t for t, u in _re2.findall(r'\[([^\]]{5,120})\]\((https?://[^\)]+)\)', text)}
                        for item in grounded:
                            url = item["url"]
                            if url not in seen_urls:
                                from urllib.parse import urlparse as _up2
                                if not any(_up2(url).netloc.lstrip("www.") == b for b in _BLOCKED_DOMAINS):
                                    seen_urls.add(url)
                                    title = (text_titles2.get(url) or item["title"] or url).strip()
                                    results.append({"id": f"gemini-search:{url}", "title": title, "url": url,
                                                    "summary": "", "authors": [],
                                                    "published": datetime.now(timezone.utc).isoformat(),
                                                    "source": name, "source_category": category})
                        logger.info(f"  {name}: {len(grounded)} 条（重试成功）")
                    except Exception as e2:
                        logger.warning(f"Gemini 搜索 {name} 重试失败: {e2}")
                else:
                    logger.warning(f"Gemini 搜索 {name} 失败: {e}")

        logger.info(f"Gemini 搜索总计: {len(results)} 条")
        return results
