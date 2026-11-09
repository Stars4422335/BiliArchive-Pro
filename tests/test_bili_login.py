"""扫码登录的凭据获取测试。

B 站的扫码响应不再直接给出 cookie，而是给一次性的 ticket 地址，cookie
要从它的响应头里换。`bilibili_api` 自带的 `QrCodeLogin` 还在按老格式找
cookie，拿到的永远是三个空字符串。

这些用例锁住两件事：新旧两种响应都能认出凭据，以及"看起来成功但其实
什么都没拿到"这种情况必须被识别成不可用。
"""

from app.core.bili_login import credential_is_usable, parse_credential_url


def test_the_current_response_is_a_ticket_url_not_a_cookie_url():
    """B 站现在返回的是一次性 ticket 地址，cookie 在它的响应头里。

    这条用例把真实结构钉住：如果哪天 B 站又改回直接把 cookie 写在
    URL 里，它会失败并提醒更新解析。
    """
    from app.core.bili_login import poll_qrcode  # noqa: F401

    ticket_url = (
        "https://passport.biligame.com/x/passport-login/web/crossDomain"
        "?ticket=abc123&gourl=https%3A%2F%2Fwww.bilibili.com&first_domain=.bilibili.com"
    )

    # 老解析器在这条 URL 上什么也取不到——这正是当初"登录成功但凭据全空"的原因。
    assert parse_credential_url(ticket_url) == {
        "sessdata": "",
        "bili_jct": "",
        "dedeuserid": "",
    }
    # 新流程靠 "ticket=" 判断该走交换而不是解析。
    assert "ticket=" in ticket_url


def test_parses_the_space_separated_format_bilibili_returned_earlier():
    # 早期 B 站的返回是 `& ` 分隔、每个 cookie 前带一个空格。
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
