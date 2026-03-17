import asyncio
from bilibili_api import favorite_list, video
import random

class BiliParser:
    def __init__(self, credential):
        self.credential = credential

    async def get_favorite_list(self, media_id):
        """拉取指定收藏夹下的所有内容（含视频与图文）"""
        print(f"[*] 正在拉取收藏夹 (ID: {media_id}) 列表...")
        try:
            # 初始化收藏夹对象
            fav = favorite_list.FavoriteList(media_id=media_id, credential=self.credential)
            # 库更新：使用 get_content 获取内容，默认拉取第一页 (后续可加上 page=2 等参数翻页)
            video_list = await fav.get_content(page=1)
            
            parsed_list = []
            for item in video_list.get('medias', []):
                # type 2 是视频，12 是专栏图文
                item_type = "video" if item['type'] == 2 else "article" if item['type'] == 12 else "unknown"
                
                parsed_list.append({
                    "title": item['title'],
                    "bvid": item.get('bvid', ''),
                    "id": item['id'], # 专栏对应 cv 号
                    "type": item_type,
                    "up_name": item['upper']['name'],
                    "cover": item['cover'],
                    "intro": item['intro'],
                    "pubtime": item['pubtime']
                })
            print(f"[+] 成功拉取 {len(parsed_list)} 个收藏记录。")
            return parsed_list
        except Exception as e:
            print(f"[-] 获取收藏夹失败: {e}")
            return []

    async def check_multi_p(self, bvid):
        """检查视频是否为多 P (分集视频)，并获取所有分P信息"""
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            info = await v.get_info()
            pages = info.get('pages', [])
            
            if len(pages) > 1:
                return True, pages
            return False, pages
        except Exception as e:
            # 捕获异常：通常是因为视频已被删除/失效
            print(f"[-] 获取视频 {bvid} 详细信息失败，可能已失效: {e}")
            return False, []
