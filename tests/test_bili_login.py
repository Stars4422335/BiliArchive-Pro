"""扫码登录的凭据解析测试。

bilibili_api 自带的 QrCodeLogin 用字符串切分解析凭据 URL，B 站现在
返回的格式会让它一个字段都取不到（详见 app/core/bili_login.py）。
这些用例锁住自己那套容错解析：分隔符、字段前后的空格、cookie 名的大小写。
"""

from app.core.bili_login import credential_is_usable, parse_credential_url


def test_parses_the_space_separated_format_bilibili_returns_now():
    # B 站现在返回的是 `& ` 分隔、每个 cookie 前带一个空格。
    url = (
        "https://passport.bilibili.com/x/passport-login/web/crossDomain"
        "?DedeUserID=12345& SESSDATA=abc%2Cdef& bili_jct=ghi"
    )

    parsed = parse_credential_url(url)

    assert parsed["sessdata"] == "abc%2Cdef"
    assert parsed["bili_jct"] == "ghi"
    assert parsed["dedeuserid"] == "12345"


def test_parses_the_plain_ampersand_format():
    url = "https://passport.bilibili.com/x?SESSDATA=abc&bili_jct=def&DedeUserID=999"

    parsed = parse_credential_url(url)

    assert parsed == {
        "sessdata": "abc",
        "bili_jct": "def",
        "dedeuserid": "999",
    }


def test_parses_semicolon_separated_cookies():
    url = "https://passport.bilibili.com/x?SESSDATA=abc; bili_jct=def; DedeUserID=1"

    parsed = parse_credential_url(url)

    assert parsed["sessdata"] == "abc"
    assert parsed["bili_jct"] == "def"
    assert parsed["dedeuserid"] == "1"


def test_cookie_names_are_case_insensitive():
    url = "https://passport.bilibili.com/x?sessdata=abc&BILI_JCT=def&dedeuserid=7"

    parsed = parse_credential_url(url)

    assert parsed["sessdata"] == "abc"
    assert parsed["bili_jct"] == "def"
    assert parsed["dedeuserid"] == "7"


def test_values_containing_equals_are_kept_whole():
    url = "https://passport.bilibili.com/x?SESSDATA=a=b=c&bili_jct=def"

    parsed = parse_credential_url(url)

    assert parsed["sessdata"] == "a=b=c"


def test_empty_url_yields_empty_fields():
    parsed = parse_credential_url("")

    assert parsed == {"sessdata": "", "bili_jct": "", "dedeuserid": ""}


def test_a_credential_without_sessdata_is_not_usable():
    # 这正是 bilibili_api 那套解析失败时的产物：字段全空。
    assert credential_is_usable(None) is False
    assert credential_is_usable({"sessdata": "", "dedeuserid": ""}) is False
    assert credential_is_usable({"sessdata": "abc", "dedeuserid": ""}) is False


def test_a_credential_with_sessdata_and_uid_is_usable():
    assert credential_is_usable({"sessdata": "abc", "dedeuserid": "1"}) is True
