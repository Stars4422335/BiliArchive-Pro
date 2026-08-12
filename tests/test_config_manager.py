from pathlib import Path

import pytest

from app.core.config_manager import (
    get_local_config_path,
    load_config,
    merge_config,
)


def test_config_manager_merges_nested_local_overrides(tmp_path):
    config_path = tmp_path / "config.yaml"
    local_path = tmp_path / "private.yaml"
    config_path.write_text(
        "system:\n  plex_mode: true\n  min_disk_gb: 5\nfavorites: []\n",
        encoding="utf-8",
    )
    local_path.write_text(
        "system:\n  min_disk_gb: 9\nfavorites:\n  - id: 1\n    name: Test\n",
        encoding="utf-8",
    )

    config = load_config(config_path, local_path)

    assert config["system"] == {"plex_mode": True, "min_disk_gb": 9}
    assert config["favorites"] == [{"id": 1, "name": "Test"}]


def test_config_manager_uses_environment_local_path(monkeypatch, tmp_path):
    local_path = tmp_path / "local.yaml"
    monkeypatch.setenv("BILIARCHIVE_LOCAL_CONFIG_PATH", str(local_path))

    assert get_local_config_path(tmp_path / "config.yaml") == str(local_path)


def test_config_manager_rejects_non_mapping_override(tmp_path):
    config_path = tmp_path / "config.yaml"
    local_path = tmp_path / "config.local.yaml"
    config_path.write_text("system: {}\n", encoding="utf-8")
    local_path.write_text("- invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="顶层必须是映射结构"):
        load_config(config_path, local_path)


def test_merge_config_replaces_lists_without_mutating_unrelated_values():
    base = {"system": {"plex_mode": True, "min_disk_gb": 5}, "favorites": []}

    result = merge_config(base, {"system": {"plex_mode": False}, "favorites": [1]})

    assert result == {
        "system": {"plex_mode": False, "min_disk_gb": 5},
        "favorites": [1],
    }
