"""Scanning the 'watch later' list."""

from app.core.metadata import MetadataGenerator


class WatchLaterMixin:

    async def scan_watch_later(self):
        """扫描稍后再看列表"""
        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
            print("[*] 【全局限制】已达到最大下载数量，跳过稍后再看")
            return

        print("\n[>>>] 开始扫描: 稍后再看")
        items = await self.parser.get_watch_later_list()
        if not items:
            return

        for item in items:
            bvid = str(item.get('bvid') or '').strip()
            title = item.get('title')
            # 确定数据库主键
            db_key = self._video_asset_key(item)
            if not db_key:
                print("[!] 跳过缺少 bvid、aid 和 id 的稍后再看条目，未写入数据库。")
                continue
            db_key, local_record = self._resolve_video_record(item, db_key)

            # 【情况A：发现源端已失效的视频】
            if title == "已失效视频" or not bvid:
                if not local_record:
                    print(f"[-] 发现失效视频，本地无存档，准备创建墓碑: {db_key}")
                    tomb_path = self.path_mgr.get_video_dir("稍后再看", "已失效视频", db_key)
                    tomb_path = self.path_mgr.mark_as_deleted(tomb_path, self.config['archive_protection']['tombstone_prefix'])
                    tombstone_item = {**item, "bvid": db_key}
                    if MetadataGenerator.create_nfo(
                        tombstone_item,
                        tomb_path,
                        status="Tombstoned",
                    ):
                        self.db.update_asset(db_key, "已失效视频", "unknown", 1, tomb_path)
                    else:
                        print(f"[-] 墓碑 NFO 写入失败，未记录完成状态: {db_key}")
                elif local_record['status'] == 0:
                    print(f"[!] 警告触发：视频源端已失效，启动孤本保护: {local_record['title']}")
                    new_path = self.path_mgr.mark_as_deleted(local_record['path'], self.config['archive_protection']['mark_deleted_prefix'])
                    self.db.update_asset(db_key, local_record['title'], local_record['type'], 2, new_path)
                continue

            # 【情况B：正常视频处理】
            if local_record and local_record['status'] == 0:
                if self._should_skip_archived_video(db_key, local_record):
                    print(f"[*] 已在库中，跳过并更新存活标记: {title}")
                    self.db.update_last_check(db_key)
                    continue
                print(f"[!] 数据库记录对应媒体不完整，准备续跑修复: {title}")

            print(f"[*] 发现新视频，准备抓取: {title}")
            download_result = await self._download_video_item("稍后再看", item)

            if download_result:
                save_path, p_count = download_result
                self.db.update_asset(db_key, title, "video", 0, save_path, p_count)
                self.global_download_count += 1
                self._report_progress(
                    status="scanning",
                    phase="asset_complete",
                    source="稍后再看",
                    current_title=title,
                    current_asset=db_key,
                    downloaded_count=self.global_download_count,
                    message=f"已归档视频：{title}",
                )

                if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                    print(f"\n[✓] 【全局限制】已成功下载 {self.max_global_downloads} 个视频，测试完成！")
                    return
