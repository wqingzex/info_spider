"""报告格式化器 - 每天生成一个 Markdown 文件 output/YYYY-MM-DD.md"""
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
        lines.append(f"### [{title}]({url})" if url else f"### {title}")

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
            lines.append("")
            for ai_line in ai_analysis.split("\n"):
                if ai_line.strip():
                    lines.append(ai_line)
                    lines.append("")

        cross_refs = item.get("cross_refs", [])
        if cross_refs:
            refs_str = " | ".join(f"[{r['source']}]({r['url']})" for r in cross_refs)
            lines.append(f"\n*同主题报道: {refs_str}*")

        return "\n".join(lines)

    def generate(self, items: list[dict], date_str: str | None = None) -> Path:
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        self.base_dir.mkdir(parents=True, exist_ok=True)

        groups = self._group_by_category(items)
        total = len(items)

        md_lines = [
            f"# VLA & 具身智能日报 {date_str}",
            f"\n> 共收录 **{total}** 条内容\n",
            "## 目录\n",
        ]
        for cat, label in CATEGORY_LABELS.items():
            if cat in groups:
                md_lines.append(f"- {label}（{len(groups[cat])}）")
        md_lines.append("")

        for cat, label in CATEGORY_LABELS.items():
            if cat not in groups:
                continue
            md_lines.append(f"---\n\n## {label}\n")
            for item in groups[cat]:
                md_lines.append(self._format_item(item))
                md_lines.append("")

        md_path = self.base_dir / f"{date_str}.md"
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        logger.info(f"报告已生成: {md_path}")
        return md_path
