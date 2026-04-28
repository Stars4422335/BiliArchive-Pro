import asyncio
from bilibili_api import favorite_list, video
import random

class BiliParser:
    def __init__(self, credential, uid=None):
        self.credential = credential
        self.uid = uid

    async def get_favorite_list(self, media_id, page=1):
        """拉取指定收藏夹下的所有内容（含视频与图文）"""
        print(f"[*] 正在拉取收藏夹 (ID: {media_id}) 第 {page} 页...")
        try:
            # 初始化收藏夹对象
            fav = favorite_list.FavoriteList(media_id=media_id, credential=self.credential)
            video_list = await fav.get_content(page=page)
            
            if not video_list:
                print(f"[-] 收藏夹结构为空，可能无权限、已失效或内容为空")
                return [], False

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
            print(f"[+] 成功拉取第 {page} 页 {len(parsed_list)} 个收藏记录。")
            
            # 返回是否还有下一页的信息 (has_more)
            has_more = video_list.get("has_more", False)
            return parsed_list, has_more
        except Exception as e:
            print(f"[-] 获取收藏夹失败: {e}")
            return [], False

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

    async def get_watch_later_list(self):
        """拉取稍后再看列表的内容"""
        print(f"[*] 正在拉取稍后再看列表...")
        try:
            # 调用原生 Bilibili API
            import httpx
            url = "https://api.bilibili.com/x/v2/history/toview/web"
            cookies = self.credential.get_cookies() if self.credential else {}
            
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
            async with httpx.AsyncClient(cookies=cookies, headers=headers) as client:
                res = await client.get(url)
                data = res.json()
            
            if data.get('code') != 0:
                print(f"[-] 获取稍后再看失败: {data.get('message', '未知错误')}")
                return []
                
            video_list = data.get('data', {}).get('list', [])
            parsed_list = []
            for item in video_list:
                owner = item.get('owner', {})
                parsed_list.append({
                    "title": item.get('title', 'Unknown'),
                    "bvid": item.get('bvid', ''),
                    "id": item.get('cid', 0),
                    "type": "video",
                    "up_name": owner.get('name', 'Unknown'),
                    "cover": item.get('pic', ''),
                    "intro": item.get('desc', ''),
                    "pubtime": item.get('pubdate', 0)
                })
            
            print(f"[+] 成功拉取稍后再看，共 {len(parsed_list)} 个视频。")
            return parsed_list
        except Exception as e:
            print(f"[-] 获取稍后再看抛出异常: {e}")
            return []

    async def get_collection_list(self, season_id, page=1):
        """拉取 UP 主合集的内容"""
        print(f"[*] 正在拉取合集 (Season ID: {season_id}) 第 {page} 页...")
        try:
            import httpx
            # 这里调用解析播放列表页的 API，对 season_id 或 series_id 支持较好。
            url = f"https://api.bilibili.com/x/series/archives?mid=0&series_id={season_id}&only_normal=true&sort=desc&pn={page}&ps=30"
            # 如果 B站返回 400，可能需要替换成 polymer 路由。我们双路兼容。
            
            cookies = self.credential.get_cookies() if self.credential else {}
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
            async with httpx.AsyncClient(cookies=cookies, headers=headers) as client:
                # 尝试 series 系列路由 (合集和列表一般用这个)
                res = await client.get(url)
                data = res.json()
                
                if data.get('code') != 0:
                    # 尝试另外一种常见路由 (polymer seasons) (通常用于频道-收藏详情)
                    url2 = f"https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?mid=1&season_id={season_id}&page_num={page}&page_size=30"
                    res = await client.get(url2)
                    data = res.json()
                    
            if data.get('code') != 0:
                print(f"[-] 获取合集失败: {data.get('message', '未知错误')}")
                return [], False
                
            archives = data.get('data', {}).get('archives', [])
            if not archives:
                # 兼容不同路由的字段差异
                archives = data.get('data', {}).get('arc_audits', [])

            parsed_list = []
            for item in archives:
                # 兼容 arc 嵌套
                arc = item.get('archive', item)
                owner = arc.get('author', arc.get('owner', {}))
                parsed_list.append({
                    "title": arc.get('title', 'Unknown'),
                    "bvid": arc.get('bvid', ''),
                    "id": arc.get('id', arc.get('aid', 0)),
                    "type": "video",
                    "up_name": owner.get('name', 'Unknown'),
                    "cover": arc.get('pic', ''),
                    "intro": arc.get('desc', ''),
                    "pubtime": arc.get('pubdate', 0)
                })
                
            print(f"[+] 成功拉取合集第 {page} 页 {len(parsed_list)} 个视频。")
            
            page_info = data.get('data', {}).get('page', {})
            total = page_info.get('total', 0)
            page_num = page_info.get('page_num', page_info.get('pn', page))
            page_size = page_info.get('page_size', page_info.get('ps', 30))
            
            has_more = total > page_num * page_size
            
            return parsed_list, has_more
        except Exception as e:
            print(f"[-] 获取合集抛出异常: {e}")
            return [], False
