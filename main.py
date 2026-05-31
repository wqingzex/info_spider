#!/usr/bin/env python3
"""VLA & 具身智能信息聚合爬虫 - 主入口"""
import sys
import logging
import argparse
from datetime import datetime, timezone

import yaml

from crawlers import ArxivCrawler, RssCrawler, GithubCrawler, BlogCrawler, GeminiSearchCrawler
from processors import Deduplicator, ReportFormatter, group_items
from processors.ai_analyzer import analyze

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def load_config(config_path: str = "config/sources.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(args) -> int:
    config = load_config(args.config)
    http_cfg = config.get("http", {})
    output_cfg = config.get("output", {})
    ai_cfg = config.get("ai", {})

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info(f"=== VLA Spider 开始爬取 [{date_str}] ===")

    all_items: list[dict] = []

    # 1. arXiv 论文
    if not args.skip_arxiv:
        try:
            crawler = ArxivCrawler(config.get("arxiv", {}), http_cfg)
            items = crawler.crawl()
            all_items.extend(items)
        except Exception as e:
            logger.error(f"arXiv 爬取异常: {e}")

    # 2. RSS/RSSHub
    if not args.skip_rss:
        try:
            crawler = RssCrawler(config.get("rss", {}), http_cfg)
            items = crawler.crawl(days_back=config["arxiv"].get("days_back", 2))
            all_items.extend(items)
        except Exception as e:
            logger.error(f"RSS 爬取异常: {e}")

    # 3. GitHub
    if not args.skip_github:
        try:
            crawler = GithubCrawler(config.get("github", {}), http_cfg)
            items = crawler.crawl(days_back=7)
            all_items.extend(items)
        except Exception as e:
            logger.error(f"GitHub 爬取异常: {e}")

    # 4. 公司博客
    if not args.skip_blogs:
        try:
            crawler = BlogCrawler(config.get("blogs", []), http_cfg)
            items = crawler.crawl()
            all_items.extend(items)
        except Exception as e:
            logger.error(f"博客爬取异常: {e}")

    # 5. Gemini Search（需配置 GEMINI_API_KEY，免费）
    if not args.skip_gemini_search:
        try:
            crawler = GeminiSearchCrawler(http_cfg)
            items = crawler.crawl()
            all_items.extend(items)
        except Exception as e:
            logger.error(f"Gemini Search 异常: {e}")

    logger.info(f"爬取完成，共 {len(all_items)} 条（去重前）")

    # 6. 去重
    dedup = Deduplicator(
        output_cfg.get("seen_urls_file", "data/seen_urls.json"),
        max_size=output_cfg.get("max_seen_urls", 10000),
    )
    new_items = dedup.filter(all_items)
    logger.info(f"去重后: {len(new_items)} 条新内容")

    if not new_items:
        logger.info("今日无新内容")
        dedup.save()
        return 0

    # 7. 跨平台内容聚合（合并同主题报道）
    new_items = group_items(new_items)
    logger.info(f"聚合后: {len(new_items)} 条")

    # 8. AI 分析（可选）
    if not args.no_ai:
        new_items = analyze(new_items, ai_cfg)
        # 按相关性过滤（相关性 >= 3 才保留，只在有 AI 分析时）
        with_relevance = [i for i in new_items if "relevance" in i]
        if with_relevance:
            high_rel = [i for i in new_items if i.get("relevance", 5) >= 3]
            filtered_out = len(new_items) - len(high_rel)
            if filtered_out > 0:
                logger.info(f"AI 过滤低相关性内容: {filtered_out} 条")
            new_items = high_rel

    # 9. 生成报告
    formatter = ReportFormatter(output_cfg)
    md_path = formatter.generate(new_items, date_str)

    # 10. 保存去重记录
    dedup.save()

    logger.info(f"=== 完成 ===")
    logger.info(f"报告: {md_path}")
    logger.info(f"新内容:   {len(new_items)} 条")

    return 0


def main():
    parser = argparse.ArgumentParser(description="VLA & 具身智能信息爬虫")
    parser.add_argument("--config", default="config/sources.yaml", help="配置文件路径")
    parser.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--no-ai", action="store_true", help="跳过 AI 分析")
    parser.add_argument("--skip-arxiv", action="store_true")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--skip-github", action="store_true")
    parser.add_argument("--skip-blogs", action="store_true")
    parser.add_argument("--skip-gemini-search", action="store_true", help="跳过 Gemini Search")
    args = parser.parse_args()

    sys.exit(run(args))


if __name__ == "__main__":
    main()
