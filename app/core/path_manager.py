import os
import re

class PathManager:
    def __init__(self, root_path, plex_mode=True):
        self.root = root_path
        self.plex_mode = plex_mode

    def get_video_dir(self, fav_name, title, bvid):
        """生成安全的视频存储目录"""
        clean_title = self.sanitize_filename(title)
        safe_name = self.truncate_filename(clean_title, bvid)
        fav_dir = self.sanitize_filename(fav_name)
        return os.path.join(self.root, fav_dir, safe_name)

    def get_article_dir(self, fav_name, title, cv_id):
        """生成安全的专栏图文存储目录"""
        clean_title = self.sanitize_filename(title)
        safe_name = self.truncate_filename(clean_title, f"cv{cv_id}")
        fav_dir = self.sanitize_filename(fav_name)
        return os.path.join(self.root, fav_dir, safe_name)

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
        filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
        return filename.replace("\n", " ").strip()

    @staticmethod
    def truncate_filename(title, bvid, max_len=80):
        """防止爆路径：智能截断超长标题"""
        bvid_str = f" [{bvid}]"
        available_len = max_len - len(bvid_str)
        if len(title) > available_len:
            title = title[:available_len - 3] + "..."
        return f"{title}{bvid_str}"
