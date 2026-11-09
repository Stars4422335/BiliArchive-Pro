"""The overview panel: counts, recent assets and free disk space."""

from __future__ import annotations

import shutil
from typing import Any


class OverviewMixin:
    """The dashboard the WebUI opens on."""

    def dashboard(self) -> dict[str, Any]:
        database = self._database()
        total = database.scalar("SELECT COUNT(*) FROM assets")
        status_rows = database.query("SELECT status, COUNT(*) AS count FROM assets GROUP BY status")
        type_rows = database.query("SELECT type, COUNT(*) AS count FROM assets GROUP BY type")
        recent_rows = database.query(
            "SELECT bvid, title, type, status, path, last_check, p_count "
            "FROM assets ORDER BY last_check DESC, bvid LIMIT 10"
        )
        status_counts = {str(row["status"]): row["count"] for row in status_rows}
        type_counts = {str(row["type"] or ""): row["count"] for row in type_rows}
        runtime = self.runtime()
        return {
            "version": self.version,
            "runtime": runtime,
            # 核心引擎是否在跑。判据不是"runtime.json 存在"——那个文件在
            # 引擎停止后仍会留在磁盘上——而是它记录的状态：守护进程正常
            # 结束或被 Ctrl+C 停止时都会写 status="stopped"。
            "core_running": self._core_running(runtime),
            "assets": {
                "total": total,
                "status_counts": status_counts,
                "type_counts": type_counts,
            },
            "recent": [self._asset_record(row) for row in recent_rows],
            "storage": self.storage(),
        }

    @staticmethod
    def _core_running(runtime: dict[str, Any]) -> bool:
        """根据 runtime 状态判断核心引擎是否仍在运行。

        判据不能只看 runtime.json 是否存在——引擎停止后该文件仍留在磁盘上；
        也不能只看 status——被强杀（kill -9）会留下 status="idle" 的陈旧文件。

        组合判据：
        1. 有 stopped_at：引擎已正常退出过（正常结束、Ctrl+C、restart 命令
           都会写这个标记），因此不在运行；
        2. status 是终态（stopped / complete / error 等）：不在运行；
        3. 其余情况（scanning / idle / starting，且没有 stopped_at）：在运行。
        """
        if not runtime:
            return False
        if runtime.get("stopped_at"):
            return False
        status = str(runtime.get("status") or "").strip().lower()
        if status in {"stopped", "complete", "completed", "offline", "error", "failed"}:
            return False
        return True

    def storage(self) -> dict[str, Any]:
        configured = self.download_root()
        probe = configured
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            usage = shutil.disk_usage(probe)
            return {
                "path": str(configured),
                "exists": configured.exists(),
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "free_gb": round(usage.free / (1024**3), 3),
            }
        except OSError:
            return {"path": str(configured), "exists": configured.exists()}


__all__ = ["OverviewMixin"]
