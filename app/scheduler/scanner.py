import asyncio
from app.core.parser import BiliParser
from app.core.downloader import Downloader
from app.core.metadata import MetadataGenerator

class FavScanner:
    def __init__(self, config, credential, db, path_mgr, uid=None):
        self.config = config
        self.parser = BiliParser(credential, uid=uid)
        self.downloader = Downloader(config)
        self.db = db
        self.path_mgr = path_mgr
        self.cookie_path = config['system']['cookie_path']
        self.global_download_count = 0  # 全局下载计数器
        # 从配置读取最大下载数量，0或None表示无限制（下载全部）
        self.max_global_downloads = config.get('system', {}).get('max_downloads_per_run', 0)

    async def scan_favorite(self, fav_id, fav_name):
        # 检查全局下载限制（0或None表示无限制）
        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
            print(f"[*] 【全局限制】已达到最大下载数量({self.max_global_downloads}个)，跳过收藏夹: {fav_name}")
            return

        print(f"\n[>>>] 开始扫描收藏夹: {fav_name} (ID: {fav_id})")
        
        page = 1
        has_more = True
        consecutive_existing_count = 0
        MAX_CONSECUTIVE_EXISTING = 10 # 增量备份策略：连续10个视频/专栏已存在时，认为后续均已备份，提前停止当前收藏夹扫描

        while has_more:
            # 获取当前页内容
            items, has_more = await self.parser.get_favorite_list(fav_id, page)
            if not items:
                break

            for item in items:
                bvid = item.get('bvid')
                title = item.get('title')
                asset_type = item.get('type')

                # 确定数据库主键：视频用 bvid，专栏用 cv{id}
                if asset_type == "article":
                    db_key = f"cv{item.get('id')}"
                else:
                    db_key = bvid

                # 去数据库查一下这哥们以前下过没
                local_record = self.db.get_asset(db_key)

                # 【情况A：发现源端已失效的视频】（仅对视频类型生效，专栏 bvid 为空属正常）
                if asset_type != "article" and (title == "已失效视频" or not bvid):
                    if not local_record:
                        print(f"[-] 发现失效视频，本地无存档，准备创建墓碑: {bvid}")
                        tomb_path = self.path_mgr.get_video_dir(fav_name, "已失效视频", bvid or "unknown")
                        tomb_path = self.path_mgr.mark_as_deleted(tomb_path, self.config['archive_protection']['tombstone_prefix'])
                        MetadataGenerator.create_nfo(item, tomb_path, status="Tombstoned")
                        self.db.update_asset(bvid, "已失效视频", "unknown", 1, tomb_path)
                    elif local_record['status'] == 0:
                        print(f"[!] 警告触发：视频源端已失效，启动孤本保护: {local_record['title']}")
                        new_path = self.path_mgr.mark_as_deleted(local_record['path'], self.config['archive_protection']['mark_deleted_prefix'])
                        self.db.update_asset(bvid, local_record['title'], local_record['type'], 2, new_path)
                    continue

                # 【情况B：正常视频处理】
                if asset_type == "video":
                    if local_record and local_record['status'] == 0:
                        print(f"[*] 已在库中，跳过: {title}")
                        consecutive_existing_count += 1
                        if consecutive_existing_count >= MAX_CONSECUTIVE_EXISTING:
                            print(f"[*] 增量备份策略：连续发现 {MAX_CONSECUTIVE_EXISTING} 个已备份资产，停止扫描该收藏夹。")
                            return
                        continue
                        
                    consecutive_existing_count = 0 # 遇到新内容打断连续计数
                    print(f"[*] 发现新视频，准备抓取: {title}")
                    save_path = self.path_mgr.get_video_dir(fav_name, title, bvid)

                    # 检查多P
                    is_multi, pages = await self.parser.check_multi_p(bvid)
                    p_count = len(pages) if is_multi else 1

                    # 呼叫下载引擎
                    success = self.downloader.download_video(
                        url=f"https://www.bilibili.com/video/{bvid}",
                        save_dir=save_path,
                        file_name=self.path_mgr.truncate_filename(title, bvid),
                        cookie_file_path=self.cookie_path
                    )

                    if success:
                        MetadataGenerator.create_nfo(item, save_path, status="Active")
                        self.db.update_asset(bvid, title, "video", 0, save_path, p_count)
                        self.global_download_count += 1  # 【全局限制】计数
                        
                        # 检查是否达到全局限制（0或None表示无限制）
                        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                            print(f"\n[✓] 【全局限制】已成功下载 {self.max_global_downloads} 个视频，测试完成！")
                            return

                # 【情况C：专栏图文】
                elif asset_type == "article":
                    cv_id = item.get('id')
                    article_key = f"cv{cv_id}"  # 专栏用 cv号 作为唯一标识

                    if local_record and local_record['status'] == 0:
                        print(f"[*] 专栏已在库中，跳过: {title}")
                        consecutive_existing_count += 1
                        if consecutive_existing_count >= MAX_CONSECUTIVE_EXISTING:
                            print(f"[*] 增量备份策略：连续发现 {MAX_CONSECUTIVE_EXISTING} 个已备份资产，停止扫描该收藏夹。")
                            return
                        continue
                        
                    consecutive_existing_count = 0
                    print(f"[*] 发现新专栏图文，准备抓取: {title} ({article_key})")
                    save_path = self.path_mgr.get_article_dir(fav_name, title, cv_id)

                    # 调用专栏转 Markdown 引擎
                    success = MetadataGenerator.process_article_to_md(item, save_path)

                    if success:
                        # 同时生成 NFO 元数据（Plex 兼容）
                        MetadataGenerator.create_nfo(item, save_path, status="Active")
                        self.db.update_asset(article_key, title, "article", 0, save_path)
                        self.global_download_count += 1

                        # 检查是否达到全局限制（0或None表示无限制）
                        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                            print(f"\n[✓] 【全局限制】已成功下载 {self.max_global_downloads} 个资源，本轮结束！")
                            return
            
            # 本页处理结束，如果未触发退出条件且 has_more=True，则页码+1继续
            page += 1
            if has_more:
                print(f"[*] 准备拉取下一页...")
                await asyncio.sleep(2)  # 翻页防风控保护

