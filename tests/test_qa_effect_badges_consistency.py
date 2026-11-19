"""QA 独立验证：前端「生效徽章」表必须与后端 EFFECT_METADATA 一致。

背景（本次修的缺陷）：`SettingsView.jsx` 里的 EFFECT 表一度漏了
`download_enabled` / `quality_audit_enabled` / `disable_auth` / `min_disk_gb`
等键，于是 UI 把热重载项标成「需重启」——用户以为 P0 修好的热更新不存在。
这类"徽章漂移"的根因是**前后端各写一份表**，而此前没有任何测试把两边绑在一起。

本文件用 pytest 直接解析 JSX 源码里的 EFFECT 表，与后端
`EFFECT_METADATA` 做双向比对：
- 后端说 immediate 的键，前端必须渲染成「即时生效」；
- 后端说 restart 的键，前端必须渲染成「需重启」（反例必须成立）；
- 前端不许凭空多标 immediate；
- 每个 section 级的 immediate 归属也必须对齐。

这样漂移会在 pytest 阶段就失败，而不必等用户抱怨。
"""

import re
from pathlib import Path

from app.webui.queries.settings import EFFECT_METADATA

SETTINGS_VIEW = (
    Path(__file__).resolve().parents[1] / "webui" / "src" / "views" / "SettingsView.jsx"
)

#: 只描述"某一整节都即时生效"的占位键，不参与字段级比对。
SECTION_KEY = "__section__"

#: 特意抽查的 P0 感知面：这几个键是本次修复的核心，任何一个标错都要炸。
MUST_BE_IMMEDIATE = {
    ("system", "download_enabled"),
    ("system", "quality_audit_enabled"),
    ("system", "disable_auth"),
    ("system", "download_retries"),
    ("system", "subtitle_langs"),
    ("system", "min_disk_gb"),
}

#: 反例：这几个必须是「需重启」，否则说明整张表被一律标成即时生效。
MUST_BE_RESTART = {
    ("system", "db_wal"),
    ("system", "plex_mode"),
    ("system", "verify_integrity"),
    ("network", "github_proxy_url"),
}


def _read_view_source() -> str:
    assert SETTINGS_VIEW.is_file(), f"找不到前端设置页: {SETTINGS_VIEW}"
    return SETTINGS_VIEW.read_text(encoding="utf-8")


def _bracket_body(text: str, marker: str) -> str:
    """取 ``marker: [ ... ]`` 里方括号内的原文（按括号配平，不靠非贪婪正则）。

    非贪婪正则会在第一个元素的 ``]`` 处截断；配平扫描对"以后又加回 restart
    数组"这类改动也稳定。
    """
    marker_at = text.find(marker)
    assert marker_at >= 0, f"找不到 {marker!r}"
    open_at = text.find("[", marker_at)
    assert open_at >= 0, f"{marker!r} 后面没有数组"
    depth = 0
    for index in range(open_at, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[open_at + 1:index]
    raise AssertionError(f"{marker!r} 的数组没有闭合")


def _parse_frontend_effect_table(source: str):
    """从 JSX 源码里解析出 (immediate 字段集, 整节即时生效的 section 集)。"""
    block_match = re.search(r"const\s+EFFECT\s*=\s*\{(.*?)\n\};", source, re.DOTALL)
    assert block_match, "SettingsView.jsx 里找不到 `const EFFECT = { ... };` 表，解析需要更新"
    block = block_match.group(1)

    immediate_pairs = {
        (section, key)
        for section, key in re.findall(
            r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]',
            _bracket_body(block, "immediate:"),
        )
    }
    assert immediate_pairs, "immediate 数组解析为空，正则可能已失效"

    section_match = re.search(r"\[([^\]]*)\]\.includes\(section\)", source)
    assert section_match, "找不到 effectOf() 里的 section 级即时生效列表"
    section_immediate = set(re.findall(r'"([^"]+)"', section_match.group(1)))
    assert section_immediate, "section 级即时生效列表解析为空"

    return immediate_pairs, section_immediate


def frontend_effect(section: str, key: str, immediate_pairs, section_immediate) -> str:
    """复刻 SettingsView 的 effectOf()：命中即是即时生效，否则需重启。"""
    if (section, key) in immediate_pairs or section in section_immediate:
        return "immediate"
    return "restart"


def test_frontend_badge_table_parses():
    """解析成功性自检：正则失效时本文件必须失败，不能静默变成空集合。"""
    immediate_pairs, section_immediate = _parse_frontend_effect_table(_read_view_source())

    assert len(immediate_pairs) >= 15
    assert section_immediate == {"followings", "wordcloud", "summary", "favorites", "sync_collections"}


def test_every_backend_key_matches_the_frontend_badge():
    """双向逐键比对：后端 immediate/restart 与前端徽章必须一一对应。"""
    immediate_pairs, section_immediate = _parse_frontend_effect_table(_read_view_source())

    mismatches = []
    for backend_effect, declared in EFFECT_METADATA.items():
        for section, key in declared:
            if key == SECTION_KEY:
                continue
            actual = frontend_effect(section, key, immediate_pairs, section_immediate)
            if actual != backend_effect:
                mismatches.append(
                    f"{section}.{key}: 后端={backend_effect} 前端={actual}"
                )

    assert not mismatches, "徽章漂移（前端 EFFECT 表与后端 EFFECT_METADATA 不一致）: " + "; ".join(
        sorted(mismatches)
    )


def test_frontend_does_not_invent_immediate_keys():
    """前端不许把后端没声明为 immediate 的键标成即时生效（乐观标注）。"""
    immediate_pairs, _section_immediate = _parse_frontend_effect_table(_read_view_source())
    backend_immediate = set(EFFECT_METADATA["immediate"])

    phantom = sorted(immediate_pairs - backend_immediate)
    assert not phantom, f"前端声称即时生效但后端没有声明: {phantom}"


def test_section_level_effects_match():
    """整节即时生效的范围也要对齐（后端 __section__ 条目 vs 前端 section 列表）。"""
    _immediate_pairs, section_immediate = _parse_frontend_effect_table(_read_view_source())

    backend_sections = {
        section
        for section, key in EFFECT_METADATA["immediate"]
        if key == SECTION_KEY
    }
    backend_restart_sections = {
        section
        for section, key in EFFECT_METADATA["restart"]
        if key == SECTION_KEY
    }

    assert section_immediate == backend_sections
    assert not (section_immediate & backend_restart_sections), (
        f"同一节既被标成即时生效又被标成需重启: {sorted(section_immediate & backend_restart_sections)}"
    )


def _function_body(source: str, name: str) -> str:
    """按大括号配平取出 ``function name(...) { ... }`` 的函数体。"""
    signature = re.search(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    assert signature, f"找不到函数 {name}()"
    open_at = signature.end() - 1
    depth = 0
    for index in range(open_at, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_at + 1:index]
    raise AssertionError(f"{name}() 的函数体没有闭合")


def test_effect_of_still_returns_two_distinct_classes():
    """effectOf() 必须真的分流：只 return "immediate" 会让反例全部失效。

    源码解析拿不到渲染结果，所以这里补一道"函数里两种取值都还在"的结构断言；
    真正的渲染反例由 webui/src/test/qa-settings-badges.test.jsx 覆盖。
    """
    body = _function_body(_read_view_source(), "effectOf")

    assert '"immediate"' in body, "effectOf() 不再返回 immediate"
    assert '"restart"' in body, "effectOf() 不再返回 restart（反例失效：整页会被一律标成即时生效）"


def test_p0_badges_are_immediate_and_counterexamples_are_restart():
    """P0 感知面逐个点名，同时要求反例成立（防止整表一律标即时生效）。"""
    immediate_pairs, section_immediate = _parse_frontend_effect_table(_read_view_source())

    for section, key in sorted(MUST_BE_IMMEDIATE):
        assert frontend_effect(section, key, immediate_pairs, section_immediate) == "immediate", (
            f"{section}.{key} 必须是「即时生效」"
        )
    for section, key in sorted(MUST_BE_RESTART):
        assert frontend_effect(section, key, immediate_pairs, section_immediate) == "restart", (
            f"{section}.{key} 必须是「需重启」"
        )

    # 两类都存在 → 表不是被一律标成 immediate
    observed = {
        frontend_effect(section, key, immediate_pairs, section_immediate)
        for effect in EFFECT_METADATA.values()
        for section, key in effect
        if key != SECTION_KEY
    }
    assert observed == {"immediate", "restart"}
