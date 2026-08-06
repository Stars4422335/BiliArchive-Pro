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

    assert {"config.local.yaml", f"/{LOCAL_PLAN}", "/BiliArchive-Pro-v*.zip"} <= git_patterns
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
    } <= docker_patterns


def test_dockerfile_uses_explicit_runtime_copy_list():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY . ." not in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "config.local.yaml" not in dockerfile
    assert LOCAL_PLAN not in dockerfile


def test_release_version_is_1_1_3():
    assert __version__ == "1.1.3"
