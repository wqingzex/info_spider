"""内容聚合器 - 将不同平台报道同一事件/论文的内容合并展示"""
import re
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# 用于标题规范化的停用词
_STOP_WORDS = {
    "a", "an", "the", "for", "of", "in", "on", "to", "and", "or", "is",
    "are", "was", "were", "with", "this", "that", "from", "by", "at",
    "research", "new", "paper", "study", "model", "system", "using",
    # 中文停用词
    "的", "了", "在", "是", "和", "与", "或", "有", "为", "中", "以",
    "研究", "论文", "发布", "推出", "提出", "实现", "新",
}


def _normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^\w\s一-鿿]", " ", title)
    tokens = title.split()
    tokens = [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
    return " ".join(tokens)


def _similarity(a: str, b: str) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _extract_arxiv_id(url: str) -> str | None:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d+\.\d+)", url)
    return m.group(1) if m else None


def group_items(items: list[dict], threshold: float = 0.72) -> list[dict]:
    """
    将相似内容分组，返回 "主条目" 列表。
    主条目中会携带 cross_refs 字段，列出其他平台的报道链接。
    """
    if not items:
        return items

    # 先按 arxiv ID 精确分组
    arxiv_groups: dict[str, list[dict]] = {}
    non_arxiv: list[dict] = []

    for item in items:
        aid = _extract_arxiv_id(item.get("url", ""))
        if aid:
            arxiv_groups.setdefault(aid, []).append(item)
        else:
            non_arxiv.append(item)

    # 合并 arxiv 组：以论文本身为主，其他报道作为 cross_refs
    merged: list[dict] = []
    for aid, group in arxiv_groups.items():
        primary = next((i for i in group if "arxiv" in i.get("id", "")), group[0])
        others = [i for i in group if i is not primary]
        if others:
            primary = dict(primary)
            primary["cross_refs"] = [
                {"source": o["source"], "url": o["url"]} for o in others
            ]
        merged.append(primary)

    # 对非 arxiv 内容做标题相似度分组
    used = [False] * len(non_arxiv)
    for i, item_i in enumerate(non_arxiv):
        if used[i]:
            continue
        used[i] = True
        group_leader = dict(item_i)
        cross_refs = group_leader.get("cross_refs", [])

        for j in range(i + 1, len(non_arxiv)):
            if used[j]:
                continue
            item_j = non_arxiv[j]
            sim = _similarity(item_i["title"], item_j["title"])
            if sim >= threshold:
                used[j] = True
                cross_refs.append({"source": item_j["source"], "url": item_j["url"]})
                logger.debug(
                    f"合并 [{sim:.2f}]: {item_i['title'][:40]} ↔ {item_j['title'][:40]}"
                )

        if cross_refs:
            group_leader["cross_refs"] = cross_refs
        merged.append(group_leader)

    removed = len(items) - len(merged)
    if removed > 0:
        logger.info(f"内容聚合: {len(items)} → {len(merged)} 条（合并 {removed} 个重复报道）")

    return merged
