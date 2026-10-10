"""F3 完整性巡检：对已完成归档的媒体文件做抽样校验，防"静默损坏"。

校验分两档：
- light：文件存在、非空、头部字节符合已知媒体容器签名（纯 Python，快）
- full：在 light 基础上追加 ffmpeg 快速解码探测（准确，但耗 CPU）

设计原则：只报告，不删除。损坏的孤本也胜过没有备份；
是否重新下载由用户根据"源端是否还在"自行决定。
"""

import os
import subprocess

# 常见媒体容器/编码格式的文件头签名（偏移, 魔数）
_MEDIA_SIGNATURES = (
    (4, b"ftyp"),              # MP4/MOV/M4V：box size(4字节) 后是 ftyp
    (0, b"\x1a\x45\xdf\xa3"),  # Matroska/WebM
    (0, b"FLV"),               # Flash Video
    (0, b"RIFF"),              # AVI（RIFF 容器）
    (0, b"\x30\x26\xb2\x75"),  # MPEG-PS
    (0, b"\x00\x00\x01"),      # MPEG-ES
    (0, b"\xff\xfb"),          # MP3
    (0, b"ID3"),               # MP3 (ID3)
    (0, b"OggS"),              # OGG
)

_HEADER_PROBE_SIZE = 64


class IntegrityVerifier:
    """按配置档位校验媒体文件完整性。"""

    VALID_MODES = {"off", "light", "full"}

    def __init__(self, config):
        system_config = config.get("system", {})
        mode = str(system_config.get("verify_integrity", "off")).strip().lower()
        if mode not in self.VALID_MODES:
            print(f"[!] verify_integrity 配置无效（应为 off/light/full），已按 off 处理: {mode}")
            mode = "off"
        self.mode = mode
        self.ffmpeg_path = config.get("components", {}).get("ffmpeg", {}).get("path") or "ffmpeg"

    @property
    def enabled(self):
        return self.mode != "off"

    def verify_media_file(self, file_path):
        """校验单个媒体文件。返回 (ok: bool, reason: str)。"""
        if not file_path or not os.path.isfile(file_path):
            return False, "文件不存在"

        try:
            size = os.path.getsize(file_path)
        except OSError as exc:
            return False, f"无法读取文件大小: {exc}"
        if size <= 0:
            return False, "文件为空"

        with open(file_path, "rb") as handle:
            header = handle.read(_HEADER_PROBE_SIZE)

        if not self._header_matches(header):
            return False, "文件头不符合任何已知媒体容器签名"

        if self.mode == "full":
            return self._ffmpeg_probe(file_path)

        return True, "ok"

    @staticmethod
    def _header_matches(header):
        for offset, magic in _MEDIA_SIGNATURES:
            if len(header) >= offset + len(magic) and header[offset:offset + len(magic)] == magic:
                return True
        return False

    def _ffmpeg_probe(self, file_path):
        """ffmpeg 快速解码探测：只解前几秒，出错即判损坏。"""
        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-err_detect", "explode",
            "-i", file_path,
            "-t", "5",
            "-f", "null",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=60,
            )
        except FileNotFoundError:
            return False, "full 模式需要 ffmpeg（未找到），请安装或配置 components.ffmpeg.path"
        except subprocess.TimeoutExpired:
            return False, "ffmpeg 探测超时"
        except OSError as exc:
            return False, f"ffmpeg 调用失败: {exc}"

        if completed.returncode != 0:
            stderr_tail = completed.stderr.decode("utf-8", errors="replace").strip()
            reason = stderr_tail.splitlines()[-1] if stderr_tail else f"退出码 {completed.returncode}"
            return False, f"ffmpeg 解码报错: {reason[:120]}"
        return True, "ok"

    def verify_asset(self, asset, media_extensions=None):
        """校验一个资产目录下按 p_count 预期的媒体文件。

        命名约定与 scanner 一致：单 P 为 `标题 [bvid].ext`，
        多 P 为 `标题 [bvid-Pn].ext`。
        返回 (ok: bool, reason: str, checked: int)。
        """
        if media_extensions is None:
            media_extensions = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv", ".avi"}

        archive_path = asset.get("path")
        if not archive_path or not os.path.isdir(archive_path):
            return False, "资产目录不存在", 0

        bvid = str(asset.get("bvid") or "").strip()
        if not bvid:
            return False, "资产记录缺少 bvid", 0

        p_count = int(asset.get("p_count") or 1)
        expected_stems = set()
        if p_count <= 1:
            expected_stems.add(f"[{bvid}]")
        else:
            for part_number in range(1, p_count + 1):
                expected_stems.add(f"[{bvid}-P{part_number}]")

        found = {}
        for root, _, files in os.walk(archive_path):
            for file_name in files:
                extension = os.path.splitext(file_name)[1].lower()
                if extension not in media_extensions:
                    continue
                stem = os.path.splitext(file_name)[0]
                for expected in expected_stems:
                    if stem.endswith(expected):
                        found[expected] = os.path.join(root, file_name)
                        break

        missing = expected_stems - set(found)
        if missing:
            return False, f"缺少预期媒体文件: {sorted(missing)[:3]}", len(found)

        for expected_suffix, file_path in sorted(found.items()):
            ok, reason = self.verify_media_file(file_path)
            if not ok:
                return False, f"{expected_suffix}: {reason}", len(found)

        return True, "ok", len(found)
