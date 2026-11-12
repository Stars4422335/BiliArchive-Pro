"""Shared primitives every source scanner needs."""

import asyncio
import os
import re

from bilibili_api import aid2bvid


def login_gate_open(cookie_path) -> bool:
    """下载门禁：cookie 凭据可用才允许下载。

    游客身份下载只会拿到 480p/360p 低清晰度流且 yt-dlp 仍报告成功，
    所以必须在下载前 fail-closed 校验：cookie 文件存在且
    sessdata/dedeuserid 都非空才算登录。任何读取失败一律拒绝。
    """
    import json
    import os

    if not cookie_path or not os.path.exists(cookie_path):
        print("[-] 下载门禁：登录凭据文件不存在，拒绝下载（防止游客低清入库）。")
        return False
    try:
        with open(cookie_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"[-] 下载门禁：登录凭据读取失败，拒绝下载: {exc}")
        return False
    if not isinstance(data, dict):
        print("[-] 下载门禁：登录凭据格式无效，拒绝下载。")
        return False
    if not (str(data.get("sessdata") or "").strip() and str(data.get("dedeuserid") or "").strip()):
        print("[-] 下载门禁：登录凭据字段不完整（sessdata/dedeuserid 为空），拒绝下载。")
        return False
    return True


class ScannerBase:
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

    def _report_progress(self, **payload):
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(**payload)
        except Exception as exc:
            print(f"[!] 运行状态上报失败，扫描继续: {exc}")

    def _login_gate_open(self) -> bool:
        """下载门禁：cookie 凭据可用才允许下载（详见 login_gate_open）。"""
        return login_gate_open(getattr(self, "cookie_path", None))

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
