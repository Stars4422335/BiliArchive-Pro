"""路径穿越与 SSRF 白名单的回归测试。

这两道防线是 v1.4.0 安全加固引入的（对应 Mimosa L3 扫描的
路径穿越 ×4 与 SSRF ×2），但当时只做过一次性手工验证，没有沉淀成
自动化测试。其中 SSRF 白名单还潜伏着一个真实缺陷：裸 endswith 匹配会
把 `evil-hdslb.com`、`notbilibili.com` 这类攻击者自有域名放进白名单。
"""

import os

import pytest

from app.core.metadata import MetadataGenerator


# ---------- SSRF 域名白名单 ----------


@pytest.mark.parametrize("url", [
    "https://i0.hdslb.com/bfs/archive/cover.jpg",
    "https://i1.hdslb.com/bfs/archive/cover.jpg",
    "https://hdslb.com/x.jpg",
    "https://bilibili.com/x.jpg",
    "https://i0.bilivideo.com/x.jpg",
])
def test_trusted_cdn_hosts_are_allowed(url):
    assert MetadataGenerator._is_trusted_image_url(url) is True


@pytest.mark.parametrize("url", [
    # 伪域名：攻击者自有域名恰好以受信串结尾，裸 endswith 会误放行
    "https://evil-hdslb.com/x.jpg",
    "https://notbilibili.com/x.jpg",
    "https://my-hdslb.com.attacker.io/x.jpg",
    "https://hdslb.com.evil.io/x.jpg",
    "https://bilibili.com.evil.io/x.jpg",
    "https://xbilivideo.com/x.jpg",
    # 完全无关的域名
    "https://evil.example.com/x.jpg",
    "https://example.com/x.jpg",
    # 内网与云元数据端点
    "http://127.0.0.1/x.jpg",
    "http://localhost/x.jpg",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]/x.jpg",
    "http://10.0.0.1/x.jpg",
    "http://192.168.1.1/x.jpg",
    # 协议降级
    "http://i0.hdslb.com/x.jpg",
    "file:///etc/passwd",
    "ftp://i0.hdslb.com/x.jpg",
    # 空与畸形
    "",
    "not-a-url",
    "https://",
])
def test_untrusted_urls_are_blocked(url):
    assert MetadataGenerator._is_trusted_image_url(url) is False


def test_protocol_relative_url_is_accepted_only_after_upgrade():
    """专栏正文里常见的 //host/path 会被补成 https:，因此应放行。"""
    assert MetadataGenerator._is_trusted_image_url("https://i0.hdslb.com/x.jpg") is True


def test_trailing_dot_in_host_is_normalized():
    """FQDN 结尾的点不应让合法域名被误拒。"""
    assert MetadataGenerator._is_trusted_image_url("https://i0.hdslb.com./x.jpg") is True


def test_whitelist_matches_on_label_boundary_only():
    """明确锁定修复：子域放行、同后缀伪域名拦截。"""
    # 真子域：以 "." + 受信域 开头
    assert MetadataGenerator._is_trusted_image_url("https://img.bilibili.com/x.jpg") is True
    # 伪域名：受信串只是结尾的一部分
    assert MetadataGenerator._is_trusted_image_url("https://evil-hdslb.com/x.jpg") is False
    assert MetadataGenerator._is_trusted_image_url("https://a.b.hdslb.com.attacker.net/x.jpg") is False


# ---------- 路径穿越 ----------


def test_ensure_within_accepts_nested_path(tmp_path):
    nested = tmp_path / "a" / "b" / "c.nfo"

    result = MetadataGenerator._ensure_within(str(tmp_path), str(nested))

    assert result == str(nested)


def test_ensure_within_rejects_parent_escape(tmp_path):
    base = tmp_path / "video"
    base.mkdir()
    escape = base / ".." / ".." / "evil.nfo"

    with pytest.raises(ValueError, match="路径越界"):
        MetadataGenerator._ensure_within(str(base), str(escape))


def test_ensure_within_rejects_absolute_outside(tmp_path):
    base = tmp_path / "video"
    base.mkdir()

    with pytest.raises(ValueError, match="路径越界"):
        MetadataGenerator._ensure_within(str(base), str(tmp_path / "other.nfo"))


@pytest.mark.parametrize("traversal", [
    "../../../etc/passwd",
    "subdir/../../../outside.txt",
    "..",
    "./../../outside",
])
def test_ensure_within_rejects_traversal_variants(tmp_path, traversal):
    """平台通用的穿越写法必须被拒绝。

    这里的用例都用 POSIX 风格分隔符，因为它们在 Windows 与 Linux 上
    都是真正的路径分隔符。反斜杠写法是 Windows 专属，另有一个用例。
    """
    base = tmp_path / "media"
    base.mkdir()
    candidate = os.path.join(str(base), traversal)

    with pytest.raises(ValueError, match="路径越界"):
        MetadataGenerator._ensure_within(str(base), candidate)


@pytest.mark.skipif(
    os.name != "nt",
    reason="反斜杠只在 Windows 上是路径分隔符；在 POSIX 上它是合法文件名字符",
)
def test_ensure_within_rejects_windows_style_traversal(tmp_path):
    """Windows 上的反斜杠穿越必须被拒绝。"""
    base = tmp_path / "media"
    base.mkdir()
    candidate = os.path.join(str(base), "..\\..\\windows\\system32\\config")

    with pytest.raises(ValueError, match="路径越界"):
        MetadataGenerator._ensure_within(str(base), candidate)


def test_ensure_within_rejects_sibling_prefix_directory(tmp_path):
    """同名前缀的兄弟目录不在允许范围内：a/b 与 a/b-evil 只差一个字符。"""
    base = tmp_path / "video"
    (tmp_path / "video-evil").mkdir()
    base.mkdir()

    with pytest.raises(ValueError, match="路径越界"):
        MetadataGenerator._ensure_within(
            str(base), str(tmp_path / "video-evil" / "x.nfo")
        )


def test_ensure_within_blocks_symlink_escape(tmp_path):
    """符号链接指向外部时也必须被拒——realpath 会解析它。"""
    base = tmp_path / "media"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = base / "link"
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")

    with pytest.raises(ValueError, match="路径越界"):
        MetadataGenerator._ensure_within(str(base), str(link / "x.nfo"))


def test_ensure_within_is_applied_by_nfo_writer(tmp_path):
    """create_nfo 写入前必须调用路径校验，越界时不得写出文件。

    实际行为是"安全降级"而非抛出：_write_nfo 捕获 ValueError、打印提示
    并返回 None，让调用方按"NFO 未写入"处理，不该把异常抛到扫描流程。
    """
    from app.core.metadata import ET

    root = ET.Element("movie")
    ET.SubElement(root, "title").text = "t"

    base = tmp_path / "allowed"
    base.mkdir()
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir(exist_ok=True)
    target = outside_dir / "evil.nfo"

    result = MetadataGenerator._write_nfo(root, str(target), base_dir=str(base))

    assert result is None
    assert not target.exists()


def test_nfo_write_allows_path_inside_base(tmp_path):
    from app.core.metadata import ET

    base = tmp_path / "allowed"
    base.mkdir()
    root = ET.Element("movie")
    ET.SubElement(root, "title").text = "t"

    result = MetadataGenerator._write_nfo(root, str(base / "ok.nfo"), base_dir=str(base))

    assert result
    assert (base / "ok.nfo").exists()