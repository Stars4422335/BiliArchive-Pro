import asyncio
from bilibili_api import favorite_list, video
import random

class BiliParser:
    def __init__(self, credential, uid=None):
        self.credential = credential
        self.uid = uid

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

    async def get_user_favorite_lists(self):
        """获取用户的所有视频收藏夹列表"""
        if not self.uid:
            print("[-] 错误：未提供用户ID，无法获取收藏夹列表")
            return []
        
        print(f"[*] 正在获取用户收藏夹列表...")
        try:
            result = await favorite_list.get_video_favorite_list(
                uid=self.uid, 
                credential=self.credential
            )
            
            fav_list = result.get('list', [])
            parsed_list = []
            
            for fav in fav_list:
                parsed_list.append({
                    "id": fav['id'],
                    "fid": fav['fid'],
                    "name": fav['title'],  # 使用 name 作为统一字段名
                    "media_count": fav.get('media_count', 0),
                    "attr": fav.get('attr', 0)
                })
            
            print(f"[+] 成功获取 {len(parsed_list)} 个收藏夹")
            return parsed_list
            
        except Exception as e:
            print(f"[-] 获取收藏夹列表失败: {e}")
            return []
