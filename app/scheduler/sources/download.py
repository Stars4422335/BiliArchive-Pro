"""Downloading one video and keeping media, NFO and artwork on one layout."""

import os

from app.core.metadata import MetadataGenerator
from app.core.summary import LocalSummarizer

class DownloadMixin:

    def _attach_outline(self, item, media_dir, file_stem):
        """按配置为 NFO 准备 <outline> 摘要。失败静默跳过，绝不阻断下载。

        只做本地抽取式摘要：不外发字幕文本、不引入外部依赖。
        `summary.mode` 预留了 `llm`，但当前未实现——明确报错而不是
        静默降级，避免用户误以为内容已发送。
        """
        config = self.config.get("summary", {}) or {}
        if not config.get("enabled", False):
            return None

        mode = str(config.get("mode", "local") or "local").strip().lower()
        if mode != "local":
            print(
                f"[!] summary.mode={mode} 尚未实现（外部 API 会外发字幕文本，"
                "本项目暂不提供）。本次跳过摘要生成。"
            )
            return None

        text = self._read_subtitle_text(media_dir, file_stem)
        if not text:
            # 无字幕时退回简介：有简介总比没有强
            text = str(item.get("intro") or "")
        if not text.strip():
            return None

        try:
            max_chars = int(config.get("max_chars", 220) or 220)
        except (TypeError, ValueError):
            max_chars = 220
        try:
            outline = LocalSummarizer(max_chars=max_chars).summarize(text)
        except Exception as exc:
            print(f"[!] 摘要生成失败，已跳过: {exc}")
            return None

        if not outline:
            return None

        # item 是调用方持有的同一 dict 引用，create_nfo 会读它写 <outline>。
        # 就地写入，避免为了一个字段到处传递额外参数。
        item["outline"] = outline
        print(f"[*] 已生成内容摘要 ({len(outline)} 字)")
        return outline

    @staticmethod
    def _read_subtitle_text(media_dir, file_stem):
        """读取当前媒体同名的字幕文件文本内容。

        只匹配当前任务的文件名前缀，避免把同目录其他资产的字幕读进来
        ——与 _convert_downloaded_danmaku 的隔离策略一致。
        """
        prefix = f"{file_stem}."
        candidates = []
        try:
            entries = list(os.scandir(media_dir))
        except OSError:
            return ""
        for entry in entries:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = entry.name
            if not name.startswith(prefix):
                continue
            lowered = name.lower()
            if not lowered.endswith((".srt", ".vtt", ".ass")):
                continue
            candidates.append((0 if ".zh-hans" in lowered else 1, entry.path))
        if not candidates:
            return ""
        # 优先中文字幕
        candidates.sort()
        try:
            with open(candidates[0][1], "r", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""

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

            self._attach_outline(item, media_dir, file_name)
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

            # 摘要只为第一集生成：多P通常同主题，各集字幕差异是分集内容，
            # 逐集生成会得到近乎重复的 outline，写进每集 NFO 反而失真。
            if index == 1:
                self._attach_outline(item, media_dir, file_name)

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
