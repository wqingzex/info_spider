"""报告格式化器 - 生成 Markdown 日报"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "paper": "📄 最新论文",
    "company_intl": "🌍 国际公司动态",
    "company_cn": "🇨🇳 国内公司动态",
    "media_cn": "📰 国内行业资讯",
    "media_intl": "🌐 国际行业资讯",
    "github": "💻 GitHub 热门仓库",
    "community_cn": "💬 社区讨论",
}


class ReportFormatter:
    def __init__(self, output_config: dict):
        self.base_dir = Path(output_config.get("base_dir", "output"))

    def _group_by_category(self, items: list[dict]) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for item in items:
            cat = item.get("source_category", "unknown")
            groups.setdefault(cat, []).append(item)
        return groups

    def _format_item(self, item: dict) -> str:
        title = item.get("title", "无标题")
        url = item.get("url", "")
        source = item.get("source", "")
        published = item.get("published", "")[:10]
        summary = item.get("summary", "").strip()
        authors = item.get("authors", [])
        stars = item.get("stars")
        ai_analysis = item.get("ai_analysis", "")

        lines = []
        if url:
            lines.append(f"### [{title}]({url})")
        else:
            lines.append(f"### {title}")

        meta_parts = []
        if source:
            meta_parts.append(f"来源: **{source}**")
        if published:
            meta_parts.append(f"日期: {published}")
        if authors:
            meta_parts.append(f"作者: {', '.join(authors[:3])}")
        if stars is not None:
            meta_parts.append(f"⭐ {stars}")

        if meta_parts:
            lines.append("> " + " | ".join(meta_parts))

        if summary:
            lines.append(f"\n{summary[:200]}{'...' if len(summary) > 200 else ''}")

        if ai_analysis:
            lines.append(f"\n**AI 分析:** {ai_analysis}")

        cross_refs = item.get("cross_refs", [])
        if cross_refs:
            refs_str = " | ".join(f"[{r['source']}]({r['url']})" for r in cross_refs)
            lines.append(f"\n*同主题报道: {refs_str}*")

        return "\n".join(lines)

    def generate(self, items: list[dict], date_str: str | None = None) -> tuple[Path, Path]:
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        out_dir = self.base_dir / date_str
        out_dir.mkdir(parents=True, exist_ok=True)

        # 保存原始 JSON
        json_path = out_dir / "raw.json"
        json_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 生成 Markdown 日报
        groups = self._group_by_category(items)
        total = len(items)

        md_lines = [
            f"# VLA & 具身智能日报 {date_str}",
            f"\n> 共收录 **{total}** 条内容\n",
        ]

        # 目录
        md_lines.append("## 目录\n")
        for cat, label in CATEGORY_LABELS.items():
            if cat in groups:
                count = len(groups[cat])
                md_lines.append(f"- {label}（{count}）")
        md_lines.append("")

        # 按分类输出
        for cat, label in CATEGORY_LABELS.items():
            if cat not in groups:
                continue
            cat_items = groups[cat]
            md_lines.append(f"---\n\n## {label}\n")
            for item in cat_items:
                md_lines.append(self._format_item(item))
                md_lines.append("")

        md_content = "\n".join(md_lines)
        md_path = out_dir / "report.md"
        md_path.write_text(md_content, encoding="utf-8")

        logger.info(f"报告已生成: {md_path}")
        return md_path, json_path
