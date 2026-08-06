import os
import stat

from app.core.secure_file import atomic_write_bytes, atomic_write_text


def test_atomic_write_text_replaces_content_without_temp_files(tmp_path):
    target = tmp_path / "data" / "cookie.json"

    atomic_write_text(target, "first\n")
    atomic_write_text(target, "second\n")

    assert target.read_text(encoding="utf-8") == "second\n"
    assert list(target.parent.glob(".cookie.json.*.tmp")) == []

    if os.name != "nt":
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600


def test_atomic_write_bytes_replaces_content_without_temp_files(tmp_path):
    target = tmp_path / "bin" / "yt-dlp"

    atomic_write_bytes(target, b"first", mode=0o700)
    atomic_write_bytes(target, b"second", mode=0o700)

    assert target.read_bytes() == b"second"
    assert list(target.parent.glob(".yt-dlp.*.tmp")) == []

    if os.name != "nt":
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o700
