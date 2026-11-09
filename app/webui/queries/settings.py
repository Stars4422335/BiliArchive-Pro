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
        "scan_interval_seconds",
        "max_downloads_per_run",
        "download_timeout_seconds",
    },
    "network": {
        "sync_retry_attempts",
        "sync_retry_backoff_seconds",
        "request_timeout_seconds",
    },
    "components": {"yt-dlp", "ffmpeg"},
    "archive_protection": {"mark_deleted_prefix", "tombstone_prefix"},
    "favorites": None,
    "sync_collections": None,
}
COMPONENT_FIELDS = {"strategy"}
STRATEGIES = {"auto", "notify", "off"}
INTEGER_LIMITS = {
    ("system", "scan_interval_seconds"): (60, 31 * 24 * 60 * 60),
    ("system", "max_downloads_per_run"): (0, 1_000_000),
    ("system", "download_timeout_seconds"): (0, 7 * 24 * 60 * 60),
    ("network", "sync_retry_attempts"): (1, 10),
}
NUMBER_LIMITS = {
    ("system", "min_disk_gb"): (0, 1_000_000),
    ("network", "sync_retry_backoff_seconds"): (0, 60),
    ("network", "request_timeout_seconds"): (1, 300),
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
    if section == "system" and key in {"plex_mode", "sync_watch_later"}:
        if not isinstance(value, bool):
            raise ConfigValidationError(f"{section}.{key} 必须是布尔值")
        return value
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
                if set(item) != COMPONENT_FIELDS:
                    raise ConfigValidationError(f"组件配置必须包含 strategy: {section}.{key}")
                if item["strategy"] not in STRATEGIES:
                    raise ConfigValidationError(f"不支持的组件策略: {item['strategy']}")
                section_result[key] = {"strategy": item["strategy"]}
            else:
                section_result[key] = _validate_scalar(section, key, item)
        result[section] = section_result
    return result


def _validate_collection(section: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConfigValidationError(f"配置字段必须是数组: {section}")
    fields = {"id", "name"} if section == "favorites" else {"id", "mid", "name"}
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
                name: {"strategy": value[name].get("strategy")}
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

        effective = manager.merge_config(_safe_copy(current_raw), updates)
        public_effective = public_config(effective)
        return {
            "revision": config_revision(public_effective),
            "config": public_effective,
        }


__all__ = [
    "CONFIG_SCHEMA",
    "ConfigValidationError",
    "RevisionConflict",
    "SettingsMixin",
    "config_revision",
    "public_config",
    "validate_config_payload",
]
