#!/usr/bin/env python3
"""VLA & 具身智能信息聚合爬虫 - 主入口"""
import sys
import logging
import argparse
import subprocess
from datetime import datetime, timezone, timedelta

import yaml

from crawlers import ArxivCrawler, RssCrawler, GithubCrawler, BlogCrawler
from processors import Deduplicator, ReportFormatter, group_items
from processors.ai_analyzer import analyze

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def _git_push(date_str: str) -> None:
    try:
        subprocess.run(["git", "add", f"output/{date_str}.md", "data/seen_urls.json"], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            logger.info("git: 无新变更，跳过提交")
            return
        subprocess.run(["git", "commit", "-m", f"feat: daily crawl {date_str}"], check=True)
        result = subprocess.run(["git", "pull", "--no-rebase", "-X", "ours"], capture_output=True)
        if result.returncode != 0:
            logger.warning(f"git pull 失败: {result.stderr.decode()[:200]}")
        subprocess.run(["git", "push"], check=True)
        logger.info("git: 推送成功")
    except subprocess.CalledProcessError as e:
        logger.warning(f"git push 失败: {e}")


def load_config(config_path: str = "config/sources.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(args) -> int:
    config = load_config(args.config)
    http_cfg = config.get("http", {})
    output_cfg = config.get("output", {})
    ai_cfg = config.get("ai", {})

    # 使用北京时间（UTC+8）作为日期，与用户预期一致
    beijing_tz = timezone(timedelta(hours=8))
    date_str = args.date or datetime.now(beijing_tz).strftime("%Y-%m-%d")
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

    # 9. 生成报告
    formatter = ReportFormatter(output_cfg)
    md_path = formatter.generate(new_items, date_str)

    # 10. 保存去重记录
    dedup.save()

    # 11. 推送到 GitHub
    if not args.no_push:
        _git_push(date_str)

    logger.info(f"=== 完成 ===")
    logger.info(f"报告: {md_path}")
    logger.info(f"新内容:   {len(new_items)} 条")

    return 0


def main():
    parser = argparse.ArgumentParser(description="VLA & 具身智能信息爬虫")
    parser.add_argument("--config", default="config/sources.yaml", help="配置文件路径")
    parser.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--no-ai", action="store_true", help="跳过 AI 分析")
    parser.add_argument("--no-push", action="store_true", help="跳过 git push")
    parser.add_argument("--skip-arxiv", action="store_true")
    parser.add_argument("--skip-rss", action="store_true")
    parser.add_argument("--skip-github", action="store_true")
    parser.add_argument("--skip-blogs", action="store_true")
    args = parser.parse_args()

    sys.exit(run(args))


if __name__ == "__main__":
    main()
