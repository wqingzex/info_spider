"""去重处理器 - 基于 URL 和 ID 避免重复收录"""
import json
import logging
import hashlib
from pathlib import Path

logger = logging.getLogger(__name__)


class Deduplicator:
    def __init__(self, seen_urls_file: str, max_size: int = 10000):
        self.path = Path(seen_urls_file)
        self.max_size = max_size
        self._seen: set[str] = self._load()

    def _load(self) -> set[str]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return set(data)
            except Exception as e:
                logger.warning(f"加载去重数据失败: {e}")
        return set()

    def _key(self, item: dict) -> str:
        url = item.get("url", "")
        item_id = item.get("id", "")
        raw = url or item_id
        return hashlib.md5(raw.encode()).hexdigest()

    def filter(self, items: list[dict]) -> list[dict]:
        new_items = []
        for item in items:
            key = self._key(item)
            if key not in self._seen:
                self._seen.add(key)
                new_items.append(item)
        return new_items

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 保留最新的 max_size 条
        seen_list = list(self._seen)
        if len(seen_list) > self.max_size:
            seen_list = seen_list[-self.max_size:]
        self.path.write_text(
            json.dumps(seen_list, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )
        logger.info(f"已保存去重记录: {len(seen_list)} 条")
