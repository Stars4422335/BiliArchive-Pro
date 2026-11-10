"""Scanning the video posts of followed creators."""

from app.core.metadata import MetadataGenerator


class FollowingMixin:

    async def scan_following(self, mid, up_name=None):
        """扫描单个关注 UP 主的投稿（关注源。取关后本地资产保留不动，不做任何清除）。"""
        try:
            normalized_mid = int(mid)
        except (TypeError, ValueError):
            print(f"[-] 关注源配置的 mid 不是有效 UID，跳过: {mid}")
            return
        if normalized_mid <= 0:
            print(f"[-] 关注源配置的 mid 必须是正整数，跳过: {mid}")
            return

        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
            print(f"[*] 【全局限制】已达到最大下载数量，跳过关注源: {up_name or normalized_mid}")
            return

        # UP 主名留空时先补一次：用于目录命名与进度展示
        display_name = str(up_name or "").strip()
        if not display_name:
            try:
                info = await self.parser.get_user_info(normalized_mid)
                display_name = str(info.get("name") or f"UP_{normalized_mid}")
            except Exception as exc:
                print(f"[!] 获取 UP 主名称失败，使用 UID 命名: {normalized_mid}: {exc}")
                display_name = f"UP_{normalized_mid}"

        print(f"\n[>>>] 开始扫描关注 UP 主: {display_name} (UID: {normalized_mid})")

        page = 1
        has_more = True

        while has_more:
            items, has_more = await self.parser.get_user_videos(
                normalized_mid,
                page,
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
                    print("[!] 跳过缺少 bvid、aid 和 id 的投稿条目，未写入数据库。")
                    continue
                db_key, local_record = self._resolve_video_record(item, db_key)

                # 【情况A：源端已失效的投稿】处理语义与收藏夹一致
                if title == "已失效视频" or not bvid:
                    if not local_record:
                        print(f"[-] 发现失效投稿，本地无存档，准备创建墓碑: {db_key}")
                        tomb_path = self.path_mgr.get_video_dir(display_name, "已失效视频", db_key)
                        tomb_path = self.path_mgr.mark_as_deleted(tomb_path, self.config['archive_protection']['tombstone_prefix'])
                        tombstone_item = {**item, "bvid": db_key}
                        if MetadataGenerator.create_nfo(
                            tombstone_item,
                            tomb_path,
                            status="Tombstoned",
                        ):
                            self.db.update_asset(db_key, "已失效视频", "unknown", 1, tomb_path, source=display_name)
                        else:
                            print(f"[-] 墓碑 NFO 写入失败，未记录完成状态: {db_key}")
                    elif local_record['status'] == 0:
                        print(f"[!] 警告触发：投稿源端已失效，启动孤本保护: {local_record['title']}")
                        new_path = self.path_mgr.mark_as_deleted(local_record['path'], self.config['archive_protection']['mark_deleted_prefix'])
                        self.db.update_asset(db_key, local_record['title'], local_record['type'], 2, new_path, source=display_name)
                    continue

                # 【情况B：正常投稿处理】
                if local_record and local_record['status'] == 0:
                    if self._should_skip_archived_video(db_key, local_record):
                        print(f"[*] 已在库中，跳过并更新存活标记: {title}")
                        self.db.update_last_check(db_key)
                        continue
                    print(f"[!] 数据库记录对应媒体不完整，准备续跑修复: {title}")

                print(f"[*] 发现新投稿，准备抓取: {title}")
                download_result = await self._download_video_item(display_name, item)

                if download_result:
                    save_path, p_count = download_result
                    self.db.update_asset(db_key, title, "video", 0, save_path, p_count, source=display_name)
                    self.global_download_count += 1
                    self._report_progress(
                        status="scanning",
                        phase="asset_complete",
                        source=f"关注 {display_name}",
                        current_title=title,
                        current_asset=db_key,
                        downloaded_count=self.global_download_count,
                        message=f"已归档投稿：{title}",
                    )

                    if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                        print(f"\n[✓] 【全局限制】已成功下载 {self.max_global_downloads} 个视频，本轮结束！")
                        return

            page += 1
            if has_more:
                await self._wait_for_next_page()
