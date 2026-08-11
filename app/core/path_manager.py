import hashlib
import os
import re


class PathManager:
    MAX_PATH_LENGTH = 240
    SOURCE_DIR_MAX_LENGTH = 64
    ASSET_DIR_MAX_LENGTH = 80
    OUTPUT_FILE_MAX_LENGTH = 100
    OUTPUT_SUFFIX_RESERVE = 32
    SOURCE_TREE_RESERVE = 96
    VIDEO_OUTPUT_RESERVE = 72
    ARTICLE_OUTPUT_RESERVE = 48
    MIN_SOURCE_COMPONENT_LENGTH = 8
    WINDOWS_RESERVED_NAMES = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }

    def __init__(self, root_path, plex_mode=True):
        self.root = os.fspath(root_path)
        self.plex_mode = plex_mode
        root_length = len(os.path.abspath(self.root))
        if root_length + 1 + self.SOURCE_TREE_RESERVE > self.MAX_PATH_LENGTH:
            raise ValueError(
                "归档根目录过长，无法在保留资产唯一标识的同时满足 Windows 路径限制"
            )

    @classmethod
    def _component_budget(
        cls,
        parent_path,
        preferred_length,
        reserve=0,
        minimum_length=1,
    ):
        parent_length = len(os.path.abspath(parent_path))
        available = cls.MAX_PATH_LENGTH - parent_length - 1 - reserve
        if available < minimum_length:
            raise ValueError(
                "输出路径过长，无法完整保留媒体唯一标识；请缩短 download_path"
            )
        return min(preferred_length, available)

    @staticmethod
    def _truncate_component(value, max_len):
        value = str(value)
        if len(value) <= max_len:
            return value

        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
        suffix = f"~{digest}"
        if max_len <= len(suffix):
            return digest[:max_len]
        return f"{value[:max_len - len(suffix)]}{suffix}"

    def _source_dir(self, source_name):
        clean_name = self.sanitize_filename(source_name)
        max_len = self._component_budget(
            self.root,
            self.SOURCE_DIR_MAX_LENGTH,
            reserve=self.SOURCE_TREE_RESERVE,
            minimum_length=self.MIN_SOURCE_COMPONENT_LENGTH,
        )
        return self._truncate_component(clean_name, max_len)

    def get_video_dir(self, fav_name, title, bvid):
        """生成安全的视频存储目录"""
        clean_title = self.sanitize_filename(title)
        fav_dir = self._source_dir(fav_name)
        parent_dir = os.path.join(self.root, fav_dir)
        max_len = self._component_budget(
            parent_dir,
            self.ASSET_DIR_MAX_LENGTH,
            reserve=self.VIDEO_OUTPUT_RESERVE,
            minimum_length=len(f" [{bvid}]") + 1,
        )
        safe_name = self.truncate_filename(clean_title, bvid, max_len=max_len)
        video_dir = os.path.join(self.root, fav_dir, safe_name)
        if (
            len(os.path.abspath(video_dir)) + self.VIDEO_OUTPUT_RESERVE
            > self.MAX_PATH_LENGTH
        ):
            raise ValueError("视频目录超过 Windows 路径预算")
        return video_dir

    def get_article_dir(self, fav_name, title, cv_id):
        """生成安全的专栏图文存储目录"""
        clean_title = self.sanitize_filename(title)
        fav_dir = self._source_dir(fav_name)
        parent_dir = os.path.join(self.root, fav_dir)
        max_len = self._component_budget(
            parent_dir,
            self.ASSET_DIR_MAX_LENGTH,
            reserve=self.ARTICLE_OUTPUT_RESERVE,
            minimum_length=len(f" [cv{cv_id}]") + 1,
        )
        safe_name = self.truncate_filename(
            clean_title,
            f"cv{cv_id}",
            max_len=max_len,
        )
        article_dir = os.path.join(self.root, fav_dir, safe_name)
        if (
            len(os.path.abspath(article_dir)) + self.ARTICLE_OUTPUT_RESERVE
            > self.MAX_PATH_LENGTH
        ):
            raise ValueError("专栏目录超过 Windows 路径预算")
        return article_dir

    def get_video_output(
        self,
        video_dir,
        title,
        bvid,
        part_number=None,
        part_title=None,
        part_count=1,
    ):
        """返回单个媒体文件的目录和不含扩展名的稳定文件名。"""
        if part_count <= 1:
            identifier_suffix = f" [{bvid}]"
            max_len = self._component_budget(
                video_dir,
                self.ASSET_DIR_MAX_LENGTH,
                reserve=self.OUTPUT_SUFFIX_RESERVE,
                minimum_length=len(identifier_suffix) + 1,
            )
            file_name = self.truncate_filename(
                self.sanitize_filename(title),
                bvid,
                max_len=max_len,
            )
            self._validate_output_stem(video_dir, file_name)
            return video_dir, file_name

        if (
            not isinstance(part_number, int)
            or isinstance(part_number, bool)
            or part_number < 1
        ):
            raise ValueError("多P视频必须提供从 1 开始的分集序号")

        media_dir = (
            os.path.join(video_dir, "Season 01")
            if self.plex_mode
            else video_dir
        )
        prefix = f"S01E{part_number:02d}" if self.plex_mode else f"P{part_number:02d}"
        clean_part_title = self.sanitize_filename(part_title or f"P{part_number}")
        identifier = f"{bvid}-P{part_number}"
        identifier_suffix = f" [{identifier}]"
        max_len = self._component_budget(
            media_dir,
            self.OUTPUT_FILE_MAX_LENGTH,
            reserve=self.OUTPUT_SUFFIX_RESERVE,
            minimum_length=len(prefix) + 3 + 1 + len(identifier_suffix),
        )
        file_name = self.truncate_filename(
            f"{prefix} - {clean_part_title}",
            identifier,
            max_len=max_len,
        )
        self._validate_output_stem(media_dir, file_name)
        return media_dir, file_name

    def _validate_output_stem(self, media_dir, file_name):
        stem_path = os.path.abspath(os.path.join(media_dir, file_name))
        if len(stem_path) + self.OUTPUT_SUFFIX_RESERVE > self.MAX_PATH_LENGTH:
            raise ValueError("媒体输出文件超过 Windows 路径预算")

    def mark_as_deleted(self, current_path, prefix):
        """实现孤本保护：重命名文件夹添加警告前缀"""
        if not os.path.exists(current_path): 
            return current_path
            
        dir_name = os.path.basename(current_path)
        if not dir_name.startswith(prefix):
            new_dir_name = f"{prefix} {dir_name}"
            new_path = os.path.join(os.path.dirname(current_path), new_dir_name)
            try:
                os.rename(current_path, new_path)
                return new_path
            except Exception as e:
                print(f"[-] 目录重命名(标记资产)失败: {e}")
        return current_path

    @staticmethod
    def sanitize_filename(filename):
        """过滤 Windows/Mac 下的非法字符"""
        filename = str(filename or "")
        filename = re.sub(r'[\x00-\x1f\\/*?:"<>|]', "_", filename)
        cleaned = filename.replace("\n", " ").replace("\r", " ").strip()
        cleaned = cleaned.rstrip(" .")
        if not cleaned or cleaned in {".", ".."}:
            return "Untitled"
        if cleaned.split(".", 1)[0].upper() in PathManager.WINDOWS_RESERVED_NAMES:
            cleaned = f"_{cleaned}"
        return cleaned

    @staticmethod
    def truncate_filename(title, bvid, max_len=80):
        """防止爆路径：智能截断超长标题"""
        max_len = max(1, int(max_len))
        title = str(title or "Untitled")
        bvid_str = f" [{bvid}]"
        if len(bvid_str) >= max_len:
            raise ValueError("文件名预算不足，无法完整保留资产唯一标识")

        available_len = max(1, max_len - len(bvid_str))
        if len(title) > available_len:
            title = (
                title[:available_len]
                if available_len <= 3
                else title[:available_len - 3] + "..."
            )
        return f"{title}{bvid_str}"[:max_len]
