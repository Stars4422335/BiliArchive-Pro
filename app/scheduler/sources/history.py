"""Syncing watch history as metadata only."""

import time
class HistoryMixin:

    async def sync_watch_history(self, max_pages=50):
        """同步观看历史到 watch_history 表（仅元数据，不下载视频本体）。

        增量策略：历史按观看时间倒序返回，一旦本页最早记录早于
        max_history_days 窗口或库里已记录的最早时间，即停止翻页。
        """
        system_config = self.config.get('system', {})
        max_days = int(system_config.get('max_history_days', 90) or 0)
        window_start = 0
        if max_days > 0:
            window_start = int(time.time()) - max_days * 86400

        known_oldest = self.db.oldest_history_view_at()
        print(
            f"\n[>>>] 开始同步观看历史"
            f"（窗口 {max_days} 天，已记录最早: {known_oldest}）"
        )

        page = 1
        while page <= max_pages:
            items, has_more = await self.parser.get_watch_history(page=page)
            if not items:
                break

            new_count = 0
            reached_known = False
            for item in items:
                view_at = int(item.get("view_at") or 0)
                if window_start and view_at < window_start:
                    reached_known = True
                    continue
                if known_oldest and view_at <= known_oldest:
                    # 本页已触及上次同步的记录，视为增量已追平
                    reached_known = True
                self.db.record_watch_history(
                    item["bvid"],
                    item["title"],
                    item["up_name"],
                    view_at,
                )
                new_count += 1

            print(
                f"[*] 历史第 {page} 页写入 {new_count} 条"
                + ("（已触及已知记录，停止翻页）" if reached_known else "")
            )
            if reached_known or not has_more:
                break
            page += 1
            await self._wait_for_next_page()

        total = self.db.conn.execute(
            "SELECT COUNT(*) FROM watch_history"
        ).fetchone()[0]
        print(f"[+] 观看历史同步完成，当前共 {total} 条元数据记录。")
