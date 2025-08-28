import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

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
        self.lock_path = self.path.with_suffix(".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # ensure lock file exists
            self.lock_path.touch(exist_ok=True)
        except Exception:
            pass
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

    # Removed non-atomic in_flight() check to avoid race conditions; use begin_in_flight()

    def status_message_id(self, user_id: int) -> Optional[int]:
        data = self._read()
        entry: Dict[str, Any] = data.get(str(user_id)) or {}
        mid: Any = entry.get("status_message_id")
        if isinstance(mid, int):
            return mid
        try:
            return int(str(mid)) if mid is not None else None
        except Exception:
            return None

    def begin_in_flight(self, user_id: int) -> bool:
        """Atomically set in_flight to True if not already set. Returns True on success, False if already in flight."""
        if portalocker:
            with portalocker.Lock(str(self.lock_path), "a", timeout=5):
                data2: Dict[str, Dict[str, Any]] = self._read_nolock()
                entry2: Dict[str, Any] = data2.get(str(user_id)) or {}
                if bool(entry2.get("in_flight")):
                    return False
                entry2["in_flight"] = True
                entry2["telegram_user_id"] = int(user_id)
                entry2["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                data2[str(user_id)] = entry2
                self._write_nolock(data2)
                return True
        # Fallback without portalocker
        data3: Dict[str, Dict[str, Any]] = self._read_nolock()
        entry3: Dict[str, Any] = data3.get(str(user_id)) or {}
        if bool(entry3.get("in_flight")):
            return False
        entry3["in_flight"] = True
        entry3["telegram_user_id"] = int(user_id)
        entry3["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data3[str(user_id)] = entry3
        self._write_nolock(data3)
        return True

    # ---------- profile ----------
    def update_profile(self, user_id: int, full_name: Optional[str], username: Optional[str]) -> None:
        profile_url = None
        if username:
            profile_url = f"https://t.me/{username}"
        self._update(user_id, full_name=full_name or None, username=username or None, profile_url=profile_url)

    # ---------- limits ----------
    def can_consume_message(self, user_id: int, limit_per_day: int) -> bool:
        data = self._read()
        entry = data.get(str(user_id)) or {}
        today = time.strftime("%Y-%m-%d", time.gmtime())
        used = 0
        used_map = entry.get("daily_usage") or {}
        if isinstance(used_map, dict):
            used = int(used_map.get(today) or 0)
        return used < int(limit_per_day)

    def consume_message(self, user_id: int) -> None:
        if portalocker:
            with portalocker.Lock(str(self.lock_path), "a", timeout=5):
                data = self._read_nolock()
                entry = data.get(str(user_id)) or {}
                today = time.strftime("%Y-%m-%d", time.gmtime())
                used_map = entry.get("daily_usage") or {}
                if not isinstance(used_map, dict):
                    used_map = {}
                used_map[today] = int(used_map.get(today) or 0) + 1
                entry["daily_usage"] = used_map
                data[str(user_id)] = entry
                self._write_nolock(data)
                return
        data = self._read_nolock()
        entry = data.get(str(user_id)) or {}
        today = time.strftime("%Y-%m-%d", time.gmtime())
        used_map = entry.get("daily_usage") or {}
        if not isinstance(used_map, dict):
            used_map = {}
        used_map[today] = int(used_map.get(today) or 0) + 1
        entry["daily_usage"] = used_map
        data[str(user_id)] = entry
        self._write_nolock(data)

    # --------- internals ---------
    def _update(
        self,
        user_id: int,
        *,
        conversation_id: Optional[str] = None,
        status_message_id: Optional[int] = None,
        in_flight: Optional[bool] = None,
        full_name: Optional[str] = None,
        username: Optional[str] = None,
        profile_url: Optional[str] = None,
    ) -> None:
        if portalocker:
            with portalocker.Lock(str(self.lock_path), "a", timeout=5):
                data4: Dict[str, Dict[str, Any]] = self._read_nolock()
                entry4: Dict[str, Any] = data4.get(str(user_id)) or {}
                if conversation_id is not None:
                    entry4["conversation_id"] = conversation_id
                if status_message_id is not None or (status_message_id is None and "status_message_id" in entry4):
                    entry4["status_message_id"] = status_message_id
                if in_flight is not None:
                    entry4["in_flight"] = bool(in_flight)
                if full_name is not None:
                    entry4["full_name"] = str(full_name)
                if username is not None:
                    entry4["username"] = str(username)
                if profile_url is not None:
                    entry4["profile_url"] = str(profile_url)
                entry4["telegram_user_id"] = int(user_id)
                entry4["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                data4[str(user_id)] = entry4
                self._write_nolock(data4)
                return
        data: Dict[str, Dict[str, Any]] = self._read_nolock()
        entry2: Dict[str, Any] = data.get(str(user_id)) or {}
        if conversation_id is not None:
            entry2["conversation_id"] = conversation_id
        if status_message_id is not None or (status_message_id is None and "status_message_id" in entry2):
            entry2["status_message_id"] = status_message_id
        if in_flight is not None:
            entry2["in_flight"] = bool(in_flight)
        if full_name is not None:
            entry2["full_name"] = str(full_name)
        if username is not None:
            entry2["username"] = str(username)
        if profile_url is not None:
            entry2["profile_url"] = str(profile_url)
        entry2["telegram_user_id"] = int(user_id)
        entry2["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data[str(user_id)] = entry2
        self._write_nolock(data)

    def _read(self) -> Dict[str, Dict[str, Any]]:
        if portalocker:
            with portalocker.Lock(str(self.lock_path), "a", timeout=5):
                return self._read_nolock()
        return self._read_nolock()

    def _write(self, data: Dict[str, Dict[str, Any]]) -> None:
        if portalocker:
            with portalocker.Lock(str(self.lock_path), "a", timeout=5):
                self._write_nolock(data)
                return
        self._write_nolock(data)

    def _read_nolock(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}

    def _write_nolock(self, data: Dict[str, Dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # On Windows, replace can fail transiently; retry a few times
        for _ in range(5):
            try:
                tmp.replace(self.path)
                return
            except PermissionError:
                time.sleep(0.05)
        # last attempt or re-raise
        tmp.replace(self.path)
