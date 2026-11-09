"""Scanning the user's favourite folders."""

from app.core.metadata import MetadataGenerator

class FavoritesMixin:

    async def scan_favorite(self, fav_id, fav_name):
        # 检查全局下载限制（0或None表示无限制）
        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
            print(f"[*] 【全局限制】已达到最大下载数量({self.max_global_downloads}个)，跳过收藏夹: {fav_name}")
            return

        print(f"\n[>>>] 开始扫描收藏夹: {fav_name} (ID: {fav_id})")
        
        page = 1
        has_more = True

        while has_more:
            # 获取当前页内容
            items, has_more = await self.parser.get_favorite_list(fav_id, page)
            if not items:
                if has_more:
                    page += 1
                    await self._wait_for_next_page()
                    continue
                break

            for item in items:
                bvid = str(item.get('bvid') or '').strip()
                title = item.get('title')
                asset_type = item.get('type')
                
                # 确定数据库主键：视频用 bvid，专栏用 cv{id}
                if asset_type == "article":
                    db_key = f"cv{item.get('id')}"
                else:
                    db_key = self._video_asset_key(item)

                if not db_key:
                    print("[!] 跳过缺少 bvid、aid 和 id 的视频条目，未写入数据库。")
                    continue

                # 去数据库查一下这哥们以前下过没
                if asset_type == "article":
                    local_record = self.db.get_asset(db_key)
                else:
                    db_key, local_record = self._resolve_video_record(item, db_key)

                # 【情况A：发现源端已失效的视频】（仅对视频类型生效，专栏 bvid 为空属正常）
                if asset_type != "article" and (title == "已失效视频" or not bvid):
                    if not local_record:
                        print(f"[-] 发现失效视频，本地无存档，准备创建墓碑: {db_key}")
                        tomb_path = self.path_mgr.get_video_dir(fav_name, "已失效视频", db_key)
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
                if asset_type == "video":
                    if local_record and local_record['status'] == 0:
                        if self._should_skip_archived_video(db_key, local_record):
                            print(f"[*] 已在库中，跳过并更新存活标记: {title}")
                            self.db.update_last_check(db_key)
                            continue
                        print(f"[!] 数据库记录对应媒体不完整，准备续跑修复: {title}")
                        
                    print(f"[*] 发现新视频，准备抓取: {title}")
                    download_result = await self._download_video_item(fav_name, item)

                    if download_result:
                        save_path, p_count = download_result
                        self.db.update_asset(db_key, title, "video", 0, save_path, p_count)
                        self.global_download_count += 1  # 【全局限制】计数
                        self._report_progress(
                            status="scanning",
                            phase="asset_complete",
                            source=fav_name,
                            current_title=title,
                            current_asset=db_key,
                            downloaded_count=self.global_download_count,
                            message=f"已归档视频：{title}",
                        )
                        
                        # 检查是否达到全局限制（0或None表示无限制）
                        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                            print(f"\n[✓] 【全局限制】已成功下载 {self.max_global_downloads} 个视频，测试完成！")
                            return

                # 【情况C：专栏图文】
                elif asset_type == "article":
                    cv_id = item.get('id')
                    article_key = f"cv{cv_id}"  # 专栏用 cv号 作为唯一标识

                    if local_record and local_record['status'] == 0:
                        print(f"[*] 专栏已在库中，跳过并更新存活标记: {title}")
                        self.db.update_last_check(article_key)
                        continue
                        
                    print(f"[*] 发现新专栏图文，准备抓取: {title} ({article_key})")
                    save_path = self.path_mgr.get_article_dir(fav_name, title, cv_id)
                    self._report_progress(
                        status="scanning",
                        phase="asset",
                        source=fav_name,
                        current_title=title,
                        current_asset=article_key,
                        downloaded_count=self.global_download_count,
                        message=f"正在处理专栏：{title}",
                    )

                    # 调用专栏转 Markdown 引擎
                    success = MetadataGenerator.process_article_to_md(item, save_path)

                    if success:
                        # 同时生成 NFO 元数据（Plex 兼容）
                        nfo_path = MetadataGenerator.create_nfo(
                            item,
                            save_path,
                            status="Active",
                        )
                        if not nfo_path:
                            print(f"[-] 专栏 NFO 写入失败，未记录完成状态: {article_key}")
                            continue
                        self.db.update_asset(article_key, title, "article", 0, save_path)
                        self.global_download_count += 1
                        self._report_progress(
                            status="scanning",
                            phase="asset_complete",
                            source=fav_name,
                            current_title=title,
                            current_asset=article_key,
                            downloaded_count=self.global_download_count,
                            message=f"已归档专栏：{title}",
                        )

                        # 检查是否达到全局限制（0或None表示无限制）
                        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                            print(f"\n[✓] 【全局限制】已成功下载 {self.max_global_downloads} 个资源，本轮结束！")
                            return
            
            # 本页处理结束，如果未触发退出条件且 has_more=True，则页码+1继续
            page += 1
            if has_more:
                await self._wait_for_next_page()
