import os

import yaml


LOCAL_CONFIG_ENV = "BILIARCHIVE_LOCAL_CONFIG_PATH"


def load_yaml_mapping(path):
    with open(path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError(f"配置文件顶层必须是映射结构: {path}")
    return config


def merge_config(base, overrides):
    """递归合并配置；字典递归处理，列表和标量由覆盖配置替换。"""
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_config(base[key], value)
        else:
            base[key] = value
    return base


def get_local_config_path(config_path="config.yaml", local_config_path=None):
    if local_config_path:
        return os.path.abspath(os.fspath(local_config_path))

    environment_path = os.environ.get(LOCAL_CONFIG_ENV)
    if environment_path:
        return os.path.abspath(environment_path)

    config_directory = os.path.dirname(os.path.abspath(config_path))
    return os.path.join(config_directory, "config.local.yaml")


def load_config(config_path="config.yaml", local_config_path=None):
    config_path = os.path.abspath(os.fspath(config_path))
    config = load_yaml_mapping(config_path)
    resolved_local_path = get_local_config_path(config_path, local_config_path)
    if os.path.exists(resolved_local_path):
        merge_config(config, load_yaml_mapping(resolved_local_path))
    return config
