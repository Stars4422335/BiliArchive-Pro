import asyncio
import os
import re

from bilibili_api import aid2bvid
from app.core.parser import BiliParser
from app.core.downloader import Downloader
from app.core.metadata import MetadataGenerator


class FavScanner:
    MAX_EXPECTED_PARTS = 1000
    MEDIA_EXTENSIONS = {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4v",
        ".flv",
        ".avi",
    }

    def __init__(self, config, credential, db, path_mgr, uid=None):
        self.config = config
        network_config = config.get("network", {})
        self.parser = BiliParser(
            credential,
            uid=uid,
            retry_attempts=network_config.get("sync_retry_attempts", 3),
            retry_backoff_seconds=network_config.get(
                "sync_retry_backoff_seconds",
                2,
            ),
            request_timeout_seconds=network_config.get(
                "request_timeout_seconds",
                30,
            ),
        )
        self.downloader = Downloader(config)
        self.db = db
        self.path_mgr = path_mgr
        self.cookie_path = config['system']['cookie_path']
        self.global_download_count = 0  # 全局下载计数器
        self._progress_callback = None
        # 从配置读取最大下载数量，0或None表示无限制（下载全部）
        self.max_global_downloads = config.get('system', {}).get('max_downloads_per_run', 0)

    def set_progress_callback(self, callback):
        self._progress_callback = callback if callable(callback) else None

    def _report_progress(self, **payload):
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(**payload)
        except Exception as exc:
            print(f"[!] 运行状态上报失败，扫描继续: {exc}")

    @staticmethod
    async def _wait_for_next_page():
        await asyncio.sleep(1.5)
        print("[*] 准备拉取下一页...")
        await asyncio.sleep(2)

    @staticmethod
    def _video_aid(item):
        for field in ('aid', 'id'):
            raw_id = item.get(field)
            if raw_id is None or isinstance(raw_id, bool):
                continue
            id_text = str(raw_id).strip()
            if id_text.lower().startswith('av'):
                id_text = id_text[2:]
            if id_text.isdigit() and int(id_text) > 0:
                return int(id_text)
        return None

    @classmethod
    def _video_asset_key(cls, item):
        bvid = str(item.get('bvid') or '').strip()
        if bvid:
            return bvid

        aid = cls._video_aid(item)
        return f"av{aid}" if aid is not None else None

    def _resolve_video_record(self, item, db_key):
        local_record = self.db.get_asset(db_key)
        if local_record:
            return db_key, local_record

        aid = self._video_aid(item)
        if aid is None:
            return db_key, None

        bvid = str(item.get('bvid') or '').strip()
        alternate_key = f"av{aid}" if bvid else aid2bvid(aid)
        if alternate_key == db_key:
            return db_key, None

        alternate_record = self.db.get_asset(alternate_key)
        if alternate_record:
            return alternate_key, alternate_record
        return db_key, None

    @staticmethod
    def _page_number(page, fallback):
        raw_number = page.get("page") if isinstance(page, dict) else None
        if isinstance(raw_number, bool):
            return fallback
        try:
            page_number = int(raw_number)
        except (TypeError, ValueError):
            return fallback
        return page_number if page_number > 0 else fallback

    @staticmethod
    def _page_title(page, fallback):
        if not isinstance(page, dict):
            return fallback
        return str(page.get("part") or page.get("title") or fallback).strip() or fallback

    @classmethod
    def _video_record_is_complete(cls, local_record):
        raw_expected_count = local_record.get("p_count")
        if isinstance(raw_expected_count, bool):
            return False
        try:
            expected_count = int(raw_expected_count or 1)
        except (TypeError, ValueError):
            return False
        if not 1 <= expected_count <= cls.MAX_EXPECTED_PARTS:
            return False

        bvid = str(local_record.get("bvid") or "").strip()
        if not bvid:
            return False

        archive_path = local_record.get("path")
        if not archive_path or not os.path.isdir(archive_path):
            return False

        completed_parts = set()
        multi_part_pattern = re.compile(
            rf"\[{re.escape(bvid)}-P([1-9][0-9]*)\]$"
        )
        for root, _, files in os.walk(archive_path):
            for file_name in files:
                extension = os.path.splitext(file_name)[1].lower()
                if extension not in cls.MEDIA_EXTENSIONS:
                    continue
                file_path = os.path.join(root, file_name)
                try:
                    if os.path.getsize(file_path) <= 0:
                        continue
                except OSError:
                    continue

                stem = os.path.splitext(file_name)[0]
                if expected_count == 1:
                    if stem.endswith(f"[{bvid}]"):
                        return True
                    continue

                match = multi_part_pattern.search(stem)
                if not match:
                    continue
                part_number = int(match.group(1))
                if 1 <= part_number <= expected_count:
                    completed_parts.add(part_number)
                if len(completed_parts) == expected_count:
                    return True
        return False

    async def _download_video_item(self, source_name, item):
        """下载一个视频，并保证多P媒体、NFO 与封面使用同一布局。"""
        bvid = str(item.get("bvid") or "").strip()
        title = str(item.get("title") or "Unknown")
        self._report_progress(
            status="scanning",
            phase="asset",
            source=source_name,
            current_title=title,
            current_asset=bvid,
            downloaded_count=self.global_download_count,
            message=f"正在处理视频：{title}",
        )
        video_dir = self.path_mgr.get_video_dir(source_name, title, bvid)
        is_multi, pages = await self.parser.check_multi_p(bvid)

        if not is_multi:
            media_dir, file_name = self.path_mgr.get_video_output(
                video_dir,
                title,
                bvid,
            )
            success = self.downloader.download_video(
                url=f"https://www.bilibili.com/video/{bvid}",
                save_dir=media_dir,
                file_name=file_name,
                cookie_file_path=self.cookie_path,
            )
            if not success:
                return None

            if not MetadataGenerator.create_nfo(
                item,
                media_dir,
                status="Active",
                file_stem=file_name,
            ):
                return None
            poster_path = MetadataGenerator.copy_artwork(
                media_dir,
                file_name,
                os.path.join(video_dir, "poster.jpg"),
            )
            if not poster_path:
                print(f"[-] 视频封面整理失败，未记录完成状态: {bvid}")
                return None
            return video_dir, 1

        if not pages:
            print(f"[-] 多P视频缺少分集信息，跳过本轮完成标记: {bvid}")
            return None

        part_count = len(pages)
        for index, page in enumerate(pages, start=1):
            page_number = self._page_number(page, index)
            part_title = self._page_title(page, f"P{index}")
            media_dir, file_name = self.path_mgr.get_video_output(
                video_dir,
                title,
                bvid,
                part_number=index,
                part_title=part_title,
                part_count=part_count,
            )
            success = self.downloader.download_video(
                url=f"https://www.bilibili.com/video/{bvid}?p={page_number}",
                save_dir=media_dir,
                file_name=file_name,
                cookie_file_path=self.cookie_path,
            )
            if not success:
                print(f"[-] 多P视频第 {index}/{part_count} 集下载失败: {bvid}")
                return None

            if getattr(self.path_mgr, "plex_mode", False):
                nfo_path = MetadataGenerator.create_episode_nfo(
                    item,
                    media_dir,
                    file_name,
                    index,
                    part_title,
                )
            else:
                part_info = dict(item)
                part_info["title"] = part_title
                part_info["bvid"] = f"{bvid}-P{index}"
                nfo_path = MetadataGenerator.create_nfo(
                    part_info,
                    media_dir,
                    status="Active",
                    file_stem=file_name,
                )
            if not nfo_path:
                return None

            thumb_path = MetadataGenerator.copy_artwork(
                media_dir,
                file_name,
                os.path.join(media_dir, f"{file_name}-thumb.jpg"),
            )
            if not thumb_path:
                print(
                    f"[-] 多P视频第 {index}/{part_count} 集封面整理失败: {bvid}"
                )
                return None
            if index == 1:
                poster_path = MetadataGenerator.copy_artwork(
                    media_dir,
                    file_name,
                    os.path.join(video_dir, "poster.jpg"),
                )
                if not poster_path:
                    print(f"[-] 多P视频根封面整理失败，未记录完成状态: {bvid}")
                    return None

        if getattr(self.path_mgr, "plex_mode", False):
            if not MetadataGenerator.create_tvshow_nfo(item, video_dir):
                return None
        return video_dir, part_count

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
                        if self._video_record_is_complete(local_record):
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

    async def scan_watch_later(self):
        """扫描稍后再看列表"""
        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
            print(f"[*] 【全局限制】已达到最大下载数量，跳过稍后再看")
            return

        print(f"\n[>>>] 开始扫描: 稍后再看")
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
                if self._video_record_is_complete(local_record):
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
                            self.db.update_asset(db_key, "已失效视频", "unknown", 1, tomb_path)
                        else:
                            print(f"[-] 墓碑 NFO 写入失败，未记录完成状态: {db_key}")
                    elif local_record['status'] == 0:
                        new_path = self.path_mgr.mark_as_deleted(local_record['path'], self.config['archive_protection']['mark_deleted_prefix'])
                        self.db.update_asset(db_key, local_record['title'], local_record['type'], 2, new_path)
                    continue

                if local_record and local_record['status'] == 0:
                    if self._video_record_is_complete(local_record):
                        print(f"[*] 已在库中，跳过并更新存活标记: {title}")
                        self.db.update_last_check(db_key)
                        continue
                    print(f"[!] 数据库记录对应媒体不完整，准备续跑修复: {title}")
                    
                print(f"[*] 发现新视频，准备抓取: {title}")
                download_result = await self._download_video_item(collection_name, item)

                if download_result:
                    save_path, p_count = download_result
                    self.db.update_asset(db_key, title, "video", 0, save_path, p_count)
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

