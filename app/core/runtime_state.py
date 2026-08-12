import json
import os
import threading
from datetime import datetime, timedelta

from app.core.secure_file import atomic_write_text


def _now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def runtime_state_path(config):
    db_path = os.fspath(config.get("system", {}).get("db_path") or "")
    if not db_path or db_path == ":memory:":
        return None
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "runtime.json")


class RuntimeStateWriter:
    """Publish non-sensitive daemon progress for the read-only WebUI."""

    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))
        self._lock = threading.Lock()
        self._state = {
            "status": "starting",
            "phase": "startup",
            "source": None,
            "current_title": None,
            "current_asset": None,
            "downloaded_count": 0,
            "message": "核心引擎正在启动",
            "started_at": _now_text(),
            "updated_at": _now_text(),
            "next_scan_at": None,
        }
        self._write()

    def update(self, **changes):
        with self._lock:
            self._state.update(changes)
            self._state["updated_at"] = _now_text()
            self._write()
            return dict(self._state)

    def schedule_next_scan(self, seconds, **changes):
        next_scan = datetime.now().astimezone() + timedelta(seconds=max(0, seconds))
        changes["next_scan_at"] = next_scan.isoformat(timespec="seconds")
        return self.update(**changes)

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _write(self):
        payload = json.dumps(self._state, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.path, payload)
