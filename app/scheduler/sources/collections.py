"""Scanning a creator's collection (season/series)."""

from app.core.metadata import MetadataGenerator


class CollectionsMixin:

    async def scan_collection(self, collection_id, collection_name, mid):
        """扫描UP主的合集列表"""
        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
            print(f"[*] 【全局限制】已达到最大下载数量，跳过合集: {collection_name}")
            return

        print(f"\n[>>>] 开始扫描合集: {collection_name} (ID: {collection_id})")

        page = 1
        has_more = True

        while has_more:
            items, has_more = await self.parser.get_collection_list(
                collection_id,
                page,
                mid=mid,
            )
            if not items:
                if has_more:
                    page += 1
                    await self._wait_for_next_page()
                    continue
                break

            for item in items:
                bvid = str(item.get('bvid') or '').strip()
                title = item.get('title')
                db_key = self._video_asset_key(item)
                if not db_key:
                    print("[!] 跳过缺少 bvid、aid 和 id 的合集条目，未写入数据库。")
                    continue
                db_key, local_record = self._resolve_video_record(item, db_key)

                if title == "已失效视频" or not bvid:
                    if not local_record:
                        tomb_path = self.path_mgr.get_video_dir(collection_name, "已失效视频", db_key)
                        tomb_path = self.path_mgr.mark_as_deleted(tomb_path, self.config['archive_protection']['tombstone_prefix'])
                        tombstone_item = {**item, "bvid": db_key}
                        if MetadataGenerator.create_nfo(
                            tombstone_item,
                            tomb_path,
                            status="Tombstoned",
                        ):
                            self.db.update_asset(db_key, "已失效视频", "unknown", 1, tomb_path, source=collection_name)
                        else:
                            print(f"[-] 墓碑 NFO 写入失败，未记录完成状态: {db_key}")
                    elif local_record['status'] == 0:
                        new_path = self.path_mgr.mark_as_deleted(local_record['path'], self.config['archive_protection']['mark_deleted_prefix'])
                        self.db.update_asset(db_key, local_record['title'], local_record['type'], 2, new_path, source=collection_name)
                    continue

                if local_record and local_record['status'] == 0:
                    if self._should_skip_archived_video(db_key, local_record):
                        print(f"[*] 已在库中，跳过并更新存活标记: {title}")
                        self.db.update_last_check(db_key)
                        continue
                    print(f"[!] 数据库记录对应媒体不完整，准备续跑修复: {title}")

                print(f"[*] 发现新视频，准备抓取: {title}")
                download_result = await self._download_video_item(collection_name, item)

                if download_result:
                    save_path, p_count = download_result
                    self.db.update_asset(db_key, title, "video", 0, save_path, p_count, source=collection_name)
                    self.global_download_count += 1
                    self._report_progress(
                        status="scanning",
                        phase="asset_complete",
                        source=collection_name,
                        current_title=title,
                        current_asset=db_key,
                        downloaded_count=self.global_download_count,
                        message=f"已归档视频：{title}",
                    )

                    if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                        print(f"\n[✓] 【全局限制】已成功下载 {self.max_global_downloads} 个资源，本轮结束！")
                        return

            page += 1
            if has_more:
                await self._wait_for_next_page()
