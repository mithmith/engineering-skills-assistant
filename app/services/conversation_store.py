import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConversationStore:
    """
    Простое файловое хранилище истории в формате JSONL (по одному файлу на диалог).
    Поддерживает произвольные записи:
      role: "user" | "assistant" | "system"
      content: str
      kind: Optional["summary" | "note" | ...]
      любые доп. поля (ts, model, response_id, meta...)
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, conversation_id: str) -> Path:
        return self.base_dir / f"{conversation_id}.jsonl"

    def load(self, conversation_id: str) -> List[Dict[str, Any]]:
        p = self._path_for(conversation_id)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()
        return [json.loads(x) for x in lines if x.strip()]

    def append(self, conversation_id: str, record: Dict[str, Any]) -> None:
        p = self._path_for(conversation_id)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --- helpers for summaries ---

    def last_assistant_response_id(self, conversation_id: str) -> Optional[str]:
        for rec in reversed(self.load(conversation_id)):
            if rec.get("role") == "assistant" and rec.get("response_id"):
                return str(rec["response_id"])
        return None

    def latest_summary(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        for rec in reversed(self.load(conversation_id)):
            if rec.get("kind") == "summary":
                return rec
        return None
