import json
from pathlib import Path

from app import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_PLAN = "本地任务计划与执行表.md"


def _patterns(path):
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_local_state_is_excluded_from_git_and_docker():
    git_patterns = _patterns(PROJECT_ROOT / ".gitignore")
    docker_patterns = _patterns(PROJECT_ROOT / ".dockerignore")

    assert {
        "config.local.yaml",
        f"/{LOCAL_PLAN}",
        "/BiliArchive-Pro-v*.zip",
        "/.playwright-cli/",
        "/output/playwright/",
    } <= git_patterns
    assert {
        ".env",
        "config.local.yaml",
        "data",
        "downloads",
        "logs",
        "bin",
        "venv",
        LOCAL_PLAN,
        "BiliArchive-Pro-v*.zip",
        ".playwright-cli",
        "output/playwright",
    } <= docker_patterns


def test_dockerfile_uses_explicit_runtime_copy_list():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY . ." not in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY main.py login.py web.py config.yaml LICENSE README.md ./" in dockerfile
    assert "COPY --from=webui-builder /webui/dist ./webui/dist" in dockerfile
    assert "config.local.yaml" not in dockerfile
    assert LOCAL_PLAN not in dockerfile


def test_release_metadata_is_1_3_0():
    expected_version = "1.3.0"
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    web_package = json.loads(
        (PROJECT_ROOT / "webui" / "package.json").read_text(encoding="utf-8")
    )

    assert __version__ == expected_version
    assert web_package["version"] == expected_version
    assert f'org.opencontainers.image.version="{expected_version}"' in dockerfile
    assert f"BILIARCHIVE_VERSION={expected_version}" in dockerfile
    assert f"Release: v{expected_version}" in readme
    assert f"最新改进（v{expected_version}）" in readme
    assert f"## [{expected_version}] - 2026-08-12" in changelog
