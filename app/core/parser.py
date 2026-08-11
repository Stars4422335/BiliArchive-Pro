import asyncio

import httpx
from bilibili_api import favorite_list, video


class SyncFetchError(RuntimeError):
    """同步列表在有限重试后仍无法读取。"""


class BiliParser:
    def __init__(
        self,
        credential,
        uid=None,
        retry_attempts=3,
        retry_backoff_seconds=2,
        request_timeout_seconds=30,
    ):
        self.credential = credential
        self.uid = uid
        self.retry_attempts = min(10, max(1, int(retry_attempts)))
        self.retry_backoff_seconds = min(
            60.0,
            max(0.0, float(retry_backoff_seconds)),
        )
        self.request_timeout_seconds = min(
            300.0,
            max(1.0, float(request_timeout_seconds)),
        )

    async def _fetch_with_retry(self, label, operation):
        last_error = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    break

                delay = min(
                    60.0,
                    self.retry_backoff_seconds * (2 ** (attempt - 1)),
                )
                print(
                    f"[!] {label}失败（{attempt}/{self.retry_attempts}）: {exc}"
                    f"；{delay:g} 秒后重试..."
                )
                if delay:
                    await asyncio.sleep(delay)

        raise SyncFetchError(
            f"{label}在 {self.retry_attempts} 次尝试后仍失败: {last_error}"
        ) from last_error

    async def get_favorite_list(self, media_id, page=1):
        """拉取指定收藏夹下的所有内容（含视频与图文）"""
        label = f"拉取收藏夹 {media_id} 第 {page} 页"
        print(f"[*] 正在{label}...")

        async def fetch():
            fav = favorite_list.FavoriteList(
                media_id=media_id,
                credential=self.credential,
            )
            video_list = await fav.get_content(page=page)
            if not isinstance(video_list, dict) or "medias" not in video_list:
                raise ValueError("收藏夹返回结构缺少 medias")

            medias = video_list["medias"]
            if not isinstance(medias, list):
                raise ValueError("收藏夹 medias 不是列表")

            parsed_list = []
            for item in medias:
                if not isinstance(item, dict):
                    raise ValueError("收藏夹条目不是映射结构")

                raw_type = item.get("type")
                if raw_type == 2:
                    item_type = "video"
                elif raw_type == 12:
                    item_type = "article"
                else:
                    print(f"[!] 跳过不支持的收藏条目类型: {raw_type}")
                    continue

                upper = item.get("upper") or {}
                if not isinstance(upper, dict):
                    upper = {}
                bvid = item.get("bvid") or ""
                title = item.get("title") or (
                    "已失效视频" if item_type == "video" and not bvid else "Unknown"
                )
                parsed_list.append(
                    {
                        "title": title,
                        "bvid": bvid,
                        "id": item.get("id") or item.get("aid") or 0,
                        "aid": item.get("aid") or item.get("id") or 0,
                        "type": item_type,
                        "up_name": upper.get("name", "Unknown"),
                        "cover": item.get("cover", ""),
                        "intro": item.get("intro", ""),
                        "pubtime": item.get("pubtime", 0),
                    }
                )

            print(f"[+] 成功拉取第 {page} 页 {len(parsed_list)} 个收藏记录。")
            return parsed_list, bool(video_list.get("has_more", False))

        return await self._fetch_with_retry(label, fetch)

    async def check_multi_p(self, bvid):
        """检查视频是否为多 P (分集视频)，并获取所有分P信息"""
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            info = await v.get_info()
            pages = info.get("pages", [])

            if len(pages) > 1:
                return True, pages
            return False, pages
        except Exception as exc:
            print(f"[-] 获取视频 {bvid} 详细信息失败，可能已失效: {exc}")
            return False, []

    async def get_user_favorite_lists(self):
        """获取用户的所有视频收藏夹列表"""
        if not self.uid:
            print("[-] 错误：未提供用户ID，无法获取收藏夹列表")
            return []

        label = "获取用户收藏夹列表"
        print(f"[*] 正在{label}...")

        async def fetch():
            result = await favorite_list.get_video_favorite_list(
                uid=self.uid,
                credential=self.credential,
            )
            if not isinstance(result, dict) or "list" not in result:
                raise ValueError("收藏夹列表返回结构缺少 list")

            fav_list = result["list"]
            if not isinstance(fav_list, list):
                raise ValueError("收藏夹 list 不是列表")

            parsed_list = []
            for fav in fav_list:
                if not isinstance(fav, dict) or "id" not in fav or "title" not in fav:
                    raise ValueError("收藏夹列表包含无效条目")
                parsed_list.append(
                    {
                        "id": fav["id"],
                        "fid": fav.get("fid", fav["id"]),
                        "name": fav["title"],
                        "media_count": fav.get("media_count", 0),
                        "attr": fav.get("attr", 0),
                    }
                )

            print(f"[+] 成功获取 {len(parsed_list)} 个收藏夹")
            return parsed_list

        return await self._fetch_with_retry(label, fetch)

    async def get_watch_later_list(self):
        """拉取稍后再看列表的内容"""
        label = "拉取稍后再看列表"
        print(f"[*] 正在{label}...")

        async def fetch():
            url = "https://api.bilibili.com/x/v2/history/toview/web"
            cookies = self.credential.get_cookies() if self.credential else {}
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            }
            async with httpx.AsyncClient(
                cookies=cookies,
                headers=headers,
                timeout=self.request_timeout_seconds,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

            if not isinstance(data, dict):
                raise ValueError("稍后再看返回结构不是映射")
            if data.get("code") != 0:
                raise RuntimeError(data.get("message", "未知错误"))

            payload = data.get("data") or {}
            if not isinstance(payload, dict):
                raise ValueError("稍后再看 data 不是映射")
            video_list = payload.get("list", [])
            if not isinstance(video_list, list):
                raise ValueError("稍后再看 list 不是列表")

            parsed_list = []
            for item in video_list:
                if not isinstance(item, dict):
                    raise ValueError("稍后再看包含无效条目")
                owner = item.get("owner") or {}
                if not isinstance(owner, dict):
                    owner = {}
                aid = item.get("aid") or item.get("id") or 0
                parsed_list.append(
                    {
                        "title": item.get("title") or (
                            "已失效视频" if not item.get("bvid") else "Unknown"
                        ),
                        "bvid": item.get("bvid") or "",
                        "id": aid,
                        "aid": aid,
                        "type": "video",
                        "up_name": owner.get("name", "Unknown"),
                        "cover": item.get("pic", ""),
                        "intro": item.get("desc", ""),
                        "pubtime": item.get("pubdate", 0),
                    }
                )

            print(f"[+] 成功拉取稍后再看，共 {len(parsed_list)} 个视频。")
            return parsed_list

        return await self._fetch_with_retry(label, fetch)

    async def get_collection_list(self, season_id, page=1, mid=None):
        """拉取 UP 主合集的内容"""
        try:
            normalized_mid = int(mid)
        except (TypeError, ValueError) as exc:
            raise ValueError("合集 mid 必须是正整数 UP 主 UID") from exc
        if normalized_mid <= 0:
            raise ValueError("合集 mid 必须是正整数 UP 主 UID")

        label = f"拉取合集 {season_id} 第 {page} 页"
        print(f"[*] 正在{label}...")

        async def fetch():
            urls = [
                (
                    "https://api.bilibili.com/x/series/archives"
                    f"?mid={normalized_mid}&series_id={season_id}"
                    "&only_normal=true&sort=desc"
                    f"&pn={page}&ps=30"
                ),
                (
                    "https://api.bilibili.com/x/polymer/web-space/"
                    "seasons_archives_list"
                    f"?mid={normalized_mid}&season_id={season_id}"
                    f"&page_num={page}&page_size=30"
                ),
            ]
            cookies = self.credential.get_cookies() if self.credential else {}
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            }
            errors = []
            data = None
            async with httpx.AsyncClient(
                cookies=cookies,
                headers=headers,
                timeout=self.request_timeout_seconds,
            ) as client:
                for url in urls:
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        candidate = response.json()
                        if not isinstance(candidate, dict):
                            raise ValueError("合集返回结构不是映射")
                        if candidate.get("code") == 0:
                            data = candidate
                            break
                        errors.append(str(candidate.get("message", "未知错误")))
                    except Exception as exc:
                        errors.append(str(exc))

            if data is None:
                raise RuntimeError("合集 API 均读取失败: " + "; ".join(errors))

            payload = data.get("data") or {}
            if not isinstance(payload, dict):
                raise ValueError("合集 data 不是映射")
            archives = payload.get("archives") or payload.get("arc_audits") or []
            if not isinstance(archives, list):
                raise ValueError("合集 archives 不是列表")

            parsed_list = []
            for item in archives:
                if not isinstance(item, dict):
                    raise ValueError("合集包含无效条目")
                arc = item.get("archive", item)
                if not isinstance(arc, dict):
                    raise ValueError("合集 archive 不是映射")
                owner = arc.get("author", arc.get("owner", {})) or {}
                if not isinstance(owner, dict):
                    owner = {}
                parsed_list.append(
                    {
                        "title": arc.get("title") or (
                            "已失效视频" if not arc.get("bvid") else "Unknown"
                        ),
                        "bvid": arc.get("bvid") or "",
                        "id": arc.get("id") or arc.get("aid") or 0,
                        "aid": arc.get("aid") or arc.get("id") or 0,
                        "type": "video",
                        "up_name": owner.get("name", "Unknown"),
                        "cover": arc.get("pic", ""),
                        "intro": arc.get("desc", ""),
                        "pubtime": arc.get("pubdate", 0),
                    }
                )

            print(f"[+] 成功拉取合集第 {page} 页 {len(parsed_list)} 个视频。")
            page_info = payload.get("page") or {}
            if not isinstance(page_info, dict):
                raise ValueError("合集 page 不是映射")
            total = int(page_info.get("total", 0))
            page_num = int(page_info.get("page_num", page_info.get("pn", page)))
            page_size = int(page_info.get("page_size", page_info.get("ps", 30)))
            return parsed_list, total > page_num * page_size

        return await self._fetch_with_retry(label, fetch)
