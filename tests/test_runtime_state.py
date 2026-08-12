import json

from app.core.runtime_state import RuntimeStateWriter, runtime_state_path


def test_runtime_state_writer_publishes_atomic_json(tmp_path):
    state_path = tmp_path / "data" / "runtime.json"
    writer = RuntimeStateWriter(state_path)

    snapshot = writer.update(
        status="scanning",
        phase="asset",
        source="收藏夹",
        current_title="测试视频",
        current_asset="BV123",
        downloaded_count=2,
        message="正在处理视频",
    )

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted == snapshot
    assert persisted["status"] == "scanning"
    assert persisted["current_asset"] == "BV123"
    assert persisted["updated_at"]


def test_runtime_state_writer_records_next_scan_without_sleeping(tmp_path):
    writer = RuntimeStateWriter(tmp_path / "runtime.json")

    snapshot = writer.schedule_next_scan(
        60,
        status="idle",
        phase="sleeping",
        message="等待下一轮",
    )

    assert snapshot["next_scan_at"]
    assert snapshot["status"] == "idle"


def test_runtime_state_path_uses_database_directory(tmp_path):
    db_path = tmp_path / "data" / "archive.db"

    assert runtime_state_path({"system": {"db_path": str(db_path)}}) == str(
        db_path.parent / "runtime.json"
    )
    assert runtime_state_path({"system": {"db_path": ":memory:"}}) is None
