"""The configuration the WebUI is allowed to read and write.

Everything here is deliberately narrow: the WebUI never exposes a private
field, so a typo in a key is rejected instead of silently dropped, and the
local override file is the only thing it can write.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_SCHEMA = {
    "system": {
        "min_disk_gb",
        "plex_mode",
        "sync_watch_later",
        "sync_watch_history",
        "max_history_days",
        "db_wal",
        "verify_integrity",
        "check_update_on_start",
        "scan_interval_seconds",
        "max_downloads_per_run",
        "download_timeout_seconds",
    },
    "network": {
        "sync_retry_attempts",
        "sync_retry_backoff_seconds",
        "request_timeout_seconds",
        "github_proxy_url",
    },
    "components": {"yt-dlp", "ffmpeg"},
    "archive_protection": {"mark_deleted_prefix", "tombstone_prefix"},
    "followings": {"mode", "article_types", "list"},
    "wordcloud": None,
    "summary": None,
    "favorites": None,
    "sync_collections": None,
}
COMPONENT_FIELDS = {"strategy", "path"}
STRATEGIES = {"auto", "notify", "off"}
INTEGER_LIMITS = {
    ("system", "scan_interval_seconds"): (60, 31 * 24 * 60 * 60),
    ("system", "max_downloads_per_run"): (0, 1_000_000),
    ("system", "download_timeout_seconds"): (0, 7 * 24 * 60 * 60),
    ("system", "max_history_days"): (0, 3650),
    ("network", "sync_retry_attempts"): (1, 10),
}
NUMBER_LIMITS = {
    ("system", "min_disk_gb"): (0, 1_000_000),
    ("network", "sync_retry_backoff_seconds"): (0, 60),
    ("network", "request_timeout_seconds"): (1, 300),
}
BOOLEAN_KEYS = {
    ("system", "plex_mode"),
    ("system", "sync_watch_later"),
    ("system", "sync_watch_history"),
    ("system", "db_wal"),
    ("system", "check_update_on_start"),
}
VERIFY_MODES = {"off", "light", "full"}
TEXT_LIMIT_128_KEYS = {
    ("network", "github_proxy_url"),
    ("components", "__component_path__"),
    ("wordcloud", "__noop__"),
}
#: How each exposed key takes effect. ``immediate`` keys are picked up by the
#: daemon through the reload_config command channel; ``restart`` keys only
#: apply after the core process restarts. Every key in CONFIG_SCHEMA must
#: have an entry here (enforced by tests).
EFFECT_METADATA = {
    "immediate": {
        ("system", "sync_watch_later"),
        ("system", "sync_watch_history"),
        ("system", "max_history_days"),
        ("system", "check_update_on_start"),
        ("system", "scan_interval_seconds"),
        ("system", "max_downloads_per_run"),
        ("system", "download_timeout_seconds"),
        ("network", "sync_retry_attempts"),
        ("network", "sync_retry_backoff_seconds"),
        ("network", "request_timeout_seconds"),
        ("archive_protection", "mark_deleted_prefix"),
        ("archive_protection", "tombstone_prefix"),
        ("followings", "__section__"),
        ("wordcloud", "__section__"),
        ("summary", "__section__"),
        ("favorites", "__section__"),
        ("sync_collections", "__section__"),
    },
    "restart": {
        ("system", "min_disk_gb"),
        ("system", "plex_mode"),
        ("system", "db_wal"),
        ("system", "verify_integrity"),
        ("network", "github_proxy_url"),
        ("components", "__section__"),
    },
}


class ConfigValidationError(ValueError):
    """Raised when a WebUI configuration payload is outside the public schema."""


class RevisionConflict(ValueError):
    def __init__(self, revision: str):
        super().__init__("配置 revision 已变化")
        self.revision = revision


def _config_manager():
    from app.core import config_manager

    return config_manager


def _safe_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _validate_scalar(section: str, key: str, value: Any) -> Any:
    if (section, key) in BOOLEAN_KEYS:
        if not isinstance(value, bool):
            raise ConfigValidationError(f"{section}.{key} 必须是布尔值")
        return value
    if section == "system" and key == "verify_integrity":
        if value not in VERIFY_MODES:
            raise ConfigValidationError(f"{section}.{key} 必须是 off、light 或 full")
        return value
    if section == "network" and key == "github_proxy_url":
        if value is None or value == "":
            return ""
        if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 for c in value):
            raise ConfigValidationError(f"{section}.{key} 必须是不超过 256 字符的单行文本或空值")
        return value.strip()
    integer_limits = INTEGER_LIMITS.get((section, key))
    if integer_limits:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigValidationError(f"{section}.{key} 必须是整数")
        minimum, maximum = integer_limits
        if not minimum <= value <= maximum:
            raise ConfigValidationError(
                f"{section}.{key} 必须在 {minimum} 到 {maximum} 之间"
            )
        return value
    number_limits = NUMBER_LIMITS.get((section, key))
    if number_limits:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigValidationError(f"{section}.{key} 必须是数字")
        minimum, maximum = number_limits
        if not minimum <= value <= maximum:
            raise ConfigValidationError(
                f"{section}.{key} 必须在 {minimum} 到 {maximum} 之间"
            )
        return value
    if section == "archive_protection":
        if not isinstance(value, str) or not value.strip():
            raise ConfigValidationError(f"{section}.{key} 必须是非空字符串")
        if len(value) > 64 or any(ord(character) < 32 for character in value):
            raise ConfigValidationError(f"{section}.{key} 必须是不超过 64 字符的单行文本")
        return value.strip()
    return value


def validate_config_payload(payload: Any) -> dict[str, Any]:
    """Validate and copy the public configuration subset.

    This intentionally rejects unknown keys instead of silently dropping them,
    so paths, credentials, proxy settings, and future private fields cannot be
    changed through the WebUI by accident.
    """
    if not isinstance(payload, dict):
        raise ConfigValidationError("配置必须是对象")

    result: dict[str, Any] = {}
    for section, value in payload.items():
        if section not in CONFIG_SCHEMA:
            raise ConfigValidationError(f"不允许配置字段: {section}")
        allowed = CONFIG_SCHEMA[section]
        if section in {"favorites", "sync_collections"}:
            result[section] = _validate_collection(section, value)
            continue
        if section == "followings":
            result[section] = _validate_followings(value)
            continue
        if section in {"wordcloud", "summary"}:
            result[section] = _validate_simple_section(section, value)
            continue
        if not isinstance(value, dict):
            raise ConfigValidationError(f"配置分组必须是对象: {section}")
        section_result: dict[str, Any] = {}
        for key, item in value.items():
            if key not in allowed:
                raise ConfigValidationError(f"不允许配置字段: {section}.{key}")
            if section == "components":
                if not isinstance(item, dict):
                    raise ConfigValidationError(f"组件配置必须是对象: {section}.{key}")
                unknown = set(item) - COMPONENT_FIELDS
                if unknown:
                    raise ConfigValidationError(
                        f"不允许配置字段: {section}.{key}.{sorted(unknown)[0]}"
                    )
                if item["strategy"] not in STRATEGIES:
                    raise ConfigValidationError(f"不支持的组件策略: {item['strategy']}")
                component = {"strategy": item["strategy"]}
                if "path" in item:
                    path_value = item["path"]
                    if path_value not in (None, "") and (
                        not isinstance(path_value, str)
                        or len(path_value) > 256
                        or any(ord(c) < 32 for c in path_value)
                    ):
                        raise ConfigValidationError(
                            f"{section}.{key}.path 必须是不超过 256 字符的单行文本或空值"
                        )
                    component["path"] = (path_value or "").strip()
                section_result[key] = component
            else:
                section_result[key] = _validate_scalar(section, key, item)
        result[section] = section_result
    return result


FOLLOWING_MODES = {"off", "all", "list"}
ARTICLE_TYPES = {"off", "article", "all"}


def _validate_followings(value: Any) -> dict[str, Any]:
    """Validate the followings section: mode/article_types/list rows."""
    if not isinstance(value, dict):
        raise ConfigValidationError("followings 配置必须是对象")
    unknown = set(value) - {"mode", "article_types", "list"}
    if unknown:
        raise ConfigValidationError(f"不允许配置字段: followings.{sorted(unknown)[0]}")
    result: dict[str, Any] = {}
    if "mode" in value:
        if value["mode"] not in FOLLOWING_MODES:
            raise ConfigValidationError("followings.mode 必须是 off、all 或 list")
        result["mode"] = value["mode"]
    if "article_types" in value:
        if value["article_types"] not in ARTICLE_TYPES:
            raise ConfigValidationError("followings.article_types 必须是 off、article 或 all")
        result["article_types"] = value["article_types"]
    if "list" in value:
        # YAML 注释掉的空列表解析为 None，按空数组处理（与 favorites 同例）。
        result["list"] = _validate_collection(
            "followings_list", [] if value["list"] is None else value["list"]
        )
    return result


def _validate_simple_section(section: str, value: Any) -> dict[str, Any]:
    """Validate the small boolean/number sections (wordcloud, summary)."""
    if not isinstance(value, dict):
        raise ConfigValidationError(f"配置分组必须是对象: {section}")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if section == "wordcloud" and key in {"enabled"}:
            if not isinstance(item, bool):
                raise ConfigValidationError(f"{section}.{key} 必须是布尔值")
            result[key] = item
        elif section == "wordcloud" and key == "max_terms":
            if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 1000:
                raise ConfigValidationError(f"{section}.{key} 必须在 1 到 1000 之间")
            result[key] = item
        elif section == "summary" and key in {"enabled"}:
            if not isinstance(item, bool):
                raise ConfigValidationError(f"{section}.{key} 必须是布尔值")
            result[key] = item
        elif section == "summary" and key == "mode":
            if item not in {"off", "local"}:
                raise ConfigValidationError(f"{section}.{key} 必须是 off 或 local")
            result[key] = item
        elif section == "summary" and key == "max_chars":
            if isinstance(item, bool) or not isinstance(item, int) or not 50 <= item <= 10000:
                raise ConfigValidationError(f"{section}.{key} 必须在 50 到 10000 之间")
            result[key] = item
        else:
            raise ConfigValidationError(f"不允许配置字段: {section}.{key}")
    return result


def _validate_collection(section: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConfigValidationError(f"配置字段必须是数组: {section}")
    if section == "favorites":
        fields = {"id", "name"}
    elif section in {"sync_collections", "followings_list"}:
        fields = {"id", "mid", "name"} if section == "sync_collections" else {"mid", "name"}
    else:  # followings
        fields = {"mid", "name"}
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigValidationError(f"{section}[{index}] 必须是对象")
        unknown = set(item) - fields
        if unknown:
            raise ConfigValidationError(
                f"不允许配置字段: {section}[{index}].{sorted(unknown)[0]}"
            )
        if set(item) != fields:
            raise ConfigValidationError(f"{section}[{index}] 字段不完整")
        normalized = {}
        for field in fields:
            field_value = item[field]
            if field in {"id", "mid"}:
                if isinstance(field_value, bool) or not isinstance(field_value, int) or field_value <= 0:
                    raise ConfigValidationError(f"{section}[{index}].{field} 必须是正整数")
            elif not isinstance(field_value, str) or not field_value.strip():
                raise ConfigValidationError(f"{section}[{index}].{field} 必须是非空字符串")
            elif len(field_value) > 128 or any(ord(character) < 32 for character in field_value):
                raise ConfigValidationError(
                    f"{section}[{index}].{field} 必须是不超过 128 字符的单行文本"
                )
            normalized[field] = field_value.strip() if isinstance(field_value, str) else field_value
        result.append(normalized)
    return result


def public_config(config: Any) -> dict[str, Any]:
    """Return only the configuration fields exposed by the WebUI."""
    if not isinstance(config, dict):
        raise ConfigValidationError("配置必须是对象")
    filtered: dict[str, Any] = {}
    for section, allowed in CONFIG_SCHEMA.items():
        if section not in config:
            continue
        value = config[section]
        if allowed is None:
            filtered[section] = [] if value is None else value
        elif section == "components":
            filtered[section] = {
                name: {
                    key: value[name][key]
                    for key in COMPONENT_FIELDS
                    if key in value[name]
                }
                for name in allowed
                if isinstance(value, dict)
                and isinstance(value.get(name), dict)
                and "strategy" in value[name]
            }
        elif isinstance(value, dict):
            filtered[section] = {
                key: value[key] for key in allowed if key in value
            }
    return validate_config_payload(filtered)


def config_revision(config: dict[str, Any]) -> str:
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def effect_for(section: str, key: str | None = None) -> str:
    """Classify a config key as ``immediate`` or ``restart``.

    Section-level entries use the ``__section__`` sentinel: collections and
    list sections are immediate as a whole, component sections restart.
    Unknown keys default to ``restart`` (the conservative choice).
    """
    if section in {"favorites", "sync_collections", "followings", "wordcloud", "summary"}:
        return "immediate"
    if section == "components":
        return "restart"
    if (section, key) in EFFECT_METADATA["immediate"]:
        return "immediate"
    return "restart"


def effect_summary(updates: dict[str, Any]) -> dict[str, int]:
    """Count how many changed keys take effect immediately vs on restart."""
    counts = {"immediate": 0, "restart": 0}
    for section, value in updates.items():
        if isinstance(value, dict):
            for key in value:
                counts[effect_for(section, key)] += 1
        else:
            counts[effect_for(section)] += 1
    return counts


def _atomic_write_text(path: os.PathLike[str] | str, text: str) -> None:
    """Use the project's atomic writer, tolerating its current module export."""
    manager = _config_manager()
    writer = getattr(manager, "atomic_write_text", None)
    if writer is None:
        from app.core.secure_file import atomic_write_text

        writer = atomic_write_text
    writer(path, text)


class SettingsMixin:
    """Reading and writing the public configuration."""

    def load_raw_config(self) -> dict[str, Any]:
        return _config_manager().load_config(str(self.config_path))

    def load_public_config(self) -> dict[str, Any]:
        return public_config(self.load_raw_config())

    def config_response(self) -> dict[str, Any]:
        config = self.load_public_config()
        return {"revision": config_revision(config), "config": config}

    def write_config(self, incoming: dict[str, Any], expected_revision: str) -> dict[str, Any]:
        current_raw = self.load_raw_config()
        current = public_config(current_raw)
        actual_revision = config_revision(current)
        if not hmac.compare_digest(str(expected_revision), actual_revision):
            raise RevisionConflict(actual_revision)
        updates = validate_config_payload(incoming)
        manager = _config_manager()
        get_local_path = getattr(manager, "get_local_config_path", None)
        local_path = Path(
            get_local_path(str(self.config_path))
            if get_local_path
            else str(self.config_path.with_name("config.local.yaml"))
        ).resolve()
        if local_path == self.config_path:
            raise ConfigValidationError("本地覆盖配置不能与公共配置使用同一路径")

        local_config = manager.load_yaml_mapping(local_path) if local_path.exists() else {}
        local_config = manager.merge_config(_safe_copy(local_config), updates)
        text = yaml.safe_dump(local_config, allow_unicode=True, sort_keys=False)
        _atomic_write_text(local_path, text)

        self._enqueue_reload_command()

        effective = manager.merge_config(_safe_copy(current_raw), updates)
        public_effective = public_config(effective)
        return {
            "revision": config_revision(public_effective),
            "config": public_effective,
            "effects": effect_summary(updates),
        }

    def _enqueue_reload_command(self) -> None:
        """Ask the daemon to reload its in-memory config snapshot.

        Best effort: when the command channel is unavailable (standalone
        WebUI, in-memory database) saving still succeeds and the change
        applies on next restart.
        """
        try:
            from app.core.commands import open_channel

            raw = self.load_raw_config()
            channel = open_channel(raw)
            channel.enqueue("reload_config", note="settings saved via WebUI")
        except Exception:
            return


__all__ = [
    "CONFIG_SCHEMA",
    "ConfigValidationError",
    "RevisionConflict",
    "SettingsMixin",
    "config_revision",
    "public_config",
    "validate_config_payload",
]
