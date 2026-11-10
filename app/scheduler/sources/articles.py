"""Scanning the article posts of followed creators."""

from app.core.metadata import MetadataGenerator


class ArticlesMixin:

    async def scan_following_articles(self, mid, up_name=None):
        """扫描单个关注 UP 主的专栏（图文）投稿。

        与 scan_following 的语义一致：取关后本地资产保留不动，
        已归档的专栏跳过并更新存活标记，不完整记录续跑。
        专栏不走视频管线：正文按 cv 号抓取后转 Markdown + NFO。
        """
        try:
            normalized_mid = int(mid)
        except (TypeError, ValueError):
            print(f"[-] 关注源配置的 mid 不是有效 UID，跳过图文: {mid}")
            return
        if normalized_mid <= 0:
            print(f"[-] 关注源配置的 mid 必须是正整数，跳过图文: {mid}")
            return

        if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
            print(f"[*] 【全局限制】已达到最大下载数量，跳过图文源: {up_name or normalized_mid}")
            return

        display_name = str(up_name or "").strip()
        if not display_name:
            try:
                info = await self.parser.get_user_info(normalized_mid)
                display_name = str(info.get("name") or f"UP_{normalized_mid}")
            except Exception as exc:
                print(f"[!] 获取 UP 主名称失败，使用 UID 命名: {normalized_mid}: {exc}")
                display_name = f"UP_{normalized_mid}"

        print(f"\n[>>>] 开始扫描关注 UP 主图文: {display_name} (UID: {normalized_mid})")

        page = 1
        has_more = True
        while has_more:
            items, has_more = await self.parser.get_user_articles(
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
                cv_id = item.get("id")
                try:
                    cv_id = int(cv_id)
                except (TypeError, ValueError):
                    print(f"[!] 跳过无效的专栏 cv 号: {cv_id}")
                    continue
                if cv_id <= 0:
                    continue

                article_key = f"cv{cv_id}"
                title = item.get("title") or f"cv{cv_id}"
                local_record = self.db.get_asset(article_key)

                if local_record and local_record['status'] == 0:
                    print(f"[*] 专栏已在库中，跳过并更新存活标记: {title}")
                    self.db.update_last_check(article_key)
                    continue

                print(f"[*] 发现新专栏图文，准备抓取: {title} ({article_key})")
                save_path = self.path_mgr.get_article_dir(display_name, title, cv_id)
                self._report_progress(
                    status="scanning",
                    phase="asset",
                    source=f"关注图文 {display_name}",
                    current_title=title,
                    current_asset=article_key,
                    downloaded_count=self.global_download_count,
                    message=f"正在处理专栏：{title}",
                )

                success = MetadataGenerator.process_article_to_md(item, save_path)
                if not success:
                    print(f"[-] 专栏正文抓取失败，下轮重试: {article_key}")
                    continue

                nfo_path = MetadataGenerator.create_nfo(
                    item,
                    save_path,
                    status="Active",
                )
                if not nfo_path:
                    print(f"[-] 专栏 NFO 写入失败，未记录完成状态: {article_key}")
                    continue

                self.db.update_asset(article_key, title, "article", 0, save_path, source=display_name)
                self.global_download_count += 1
                self._report_progress(
                    status="scanning",
                    phase="asset_complete",
                    source=f"关注图文 {display_name}",
                    current_title=title,
                    current_asset=article_key,
                    downloaded_count=self.global_download_count,
                    message=f"已归档专栏：{title}",
                )

                if self.max_global_downloads and self.global_download_count >= self.max_global_downloads:
                    print(f"\n[✓] 【全局限制】已成功归档 {self.max_global_downloads} 个资产，本轮结束！")
                    return

            page += 1
            if has_more:
                await self._wait_for_next_page()
