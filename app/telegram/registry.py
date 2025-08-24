import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

try:
    import portalocker  # type: ignore
except Exception:  # optional dependency; naive lock fallback
    portalocker = None  # type: ignore


@dataclass
class RegistryEntry:
    telegram_user_id: int
    conversation_id: str
    status_message_id: Optional[int] = None
    in_flight: bool = False
    updated_at: str = ""


class TelegramRegistry:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    # --------- public API ---------
    def get_or_create_active_conversation(self, user_id: int, *, new_conv_id_factory) -> str:
        data = self._read()
        entry = data.get(str(user_id))
        if entry and entry.get("conversation_id"):
            return str(entry["conversation_id"])
        conv_id = str(new_conv_id_factory())
        self._update(user_id, conversation_id=conv_id)
        return conv_id

    def start_new_conversation(self, user_id: int, *, new_conv_id_factory) -> str:
        conv_id = str(new_conv_id_factory())
        self._update(user_id, conversation_id=conv_id)
        return conv_id

    def set_status(self, user_id: int, message_id: Optional[int], in_flight: bool = True) -> None:
        self._update(user_id, status_message_id=message_id, in_flight=in_flight)

    def clear_status(self, user_id: int) -> None:
        self._update(user_id, status_message_id=None, in_flight=False)

    def in_flight(self, user_id: int) -> bool:
        data = self._read()
        entry = data.get(str(user_id)) or {}
        return bool(entry.get("in_flight"))

    def status_message_id(self, user_id: int) -> Optional[int]:
        data = self._read()
        entry = data.get(str(user_id)) or {}
        mid = entry.get("status_message_id")
        return int(mid) if mid is not None else None

    # --------- internals ---------
    def _update(
        self,
        user_id: int,
        *,
        conversation_id: Optional[str] = None,
        status_message_id: Optional[int] = None,
        in_flight: Optional[bool] = None,
    ) -> None:
        data = self._read()
        entry: Dict[str, object] = data.get(str(user_id)) or {}
        if conversation_id is not None:
            entry["conversation_id"] = conversation_id
        if status_message_id is not None or (status_message_id is None and "status_message_id" in entry):
            entry["status_message_id"] = status_message_id
        if in_flight is not None:
            entry["in_flight"] = bool(in_flight)
        entry["telegram_user_id"] = int(user_id)
        entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data[str(user_id)] = entry
        self._write(data)

    def _read(self) -> Dict[str, Dict[str, object]]:
        if portalocker:
            with portalocker.Lock(str(self.path), "r", timeout=5):
                return self._read_nolock()
        return self._read_nolock()

    def _write(self, data: Dict[str, Dict[str, object]]) -> None:
        if portalocker:
            with portalocker.Lock(str(self.path), "w", timeout=5):
                self._write_nolock(data)
                return
        self._write_nolock(data)

    def _read_nolock(self) -> Dict[str, Dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}

    def _write_nolock(self, data: Dict[str, Dict[str, object]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


