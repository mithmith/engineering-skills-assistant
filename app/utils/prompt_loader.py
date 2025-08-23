import time
from pathlib import Path
from typing import Optional


class PromptLoader:
    """
    Лоадер системного промпта с «ленивым» кешированием по mtime файла.
    """

    def __init__(self, path: Path):
        self.path = path
        self._cached_text: Optional[str] = None
        self._cached_mtime: Optional[float] = None

    def load(self) -> str:
        try:
            mtime = self.path.stat().st_mtime
            if self._cached_text is None or self._cached_mtime != mtime:
                self._cached_text = self.path.read_text(encoding="utf-8")
                self._cached_mtime = mtime
            return self._cached_text or ""
        except FileNotFoundError:
            # Если файла нет — возвращаем пустой системный контекст
            return ""
