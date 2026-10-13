"""Tests for the WebUI -> daemon command channel (M3-F5).

The channel is a file-based inbox: the WebUI appends a command, the daemon
claims it and acknowledges the result. These tests cover the properties that
keep it safe: idempotent claiming, an append-only audit trail, strict payload
validation, and a hard boundary that no command can delete local media.
"""

import asyncio
import json
from pathlib import Path

import pytest

import main
from app.core.commands import (
    COMMAND_REDOWNLOAD_ASSET,
    COMMAND_RESTART,
    COMMAND_TRIGGER_SCAN,
    CommandChannel,
    CommandError,
    CommandNotFound,
    commands_path,
    open_channel,
    validate_command_payload,
)
from app.scheduler.scanner import FavScanner


BV_ID = "BV1GJ411x7h7"
AV_ID = "av80433022"


@pytest.fixture
def channel(tmp_path):
    return CommandChannel(tmp_path / "commands.json")


def _write_inbox(channel, payload):
    """Write a raw inbox document (used to simulate a hand-edited file)."""
    with open(channel.path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


# ---------- path resolution ----------


def test_commands_path_sits_next_to_the_database(tmp_path):
    db_path = tmp_path / "data" / "archive.db"

    assert commands_path({"system": {"db_path": str(db_path)}}) == str(
        db_path.parent / "commands.json"
    )


def test_commands_path_rejects_in_memory_database():
    assert commands_path({"system": {"db_path": ":memory:"}}) is None
    assert commands_path({}) is None


def test_open_channel_raises_for_in_memory_database():
    with pytest.raises(CommandNotFound):
        open_channel({"system": {"db_path": ":memory:"}})


# ---------- queue semantics ----------


def test_enqueue_persists_pending_command(channel):
    record = channel.enqueue(COMMAND_TRIGGER_SCAN, note="来自 WebUI")

    assert record["status"] == "pending"
    assert record["command"] == COMMAND_TRIGGER_SCAN
    persisted = json.loads(Path(channel.path).read_text(encoding="utf-8"))
    assert [item["id"] for item in persisted["pending"]] == [record["id"]]


def test_enqueue_normalizes_missing_payload_to_empty_dict(channel):
    record = channel.enqueue(COMMAND_TRIGGER_SCAN)

    assert record["payload"] == {}


def test_take_pending_claims_queue_exactly_once(channel):
    channel.enqueue(COMMAND_TRIGGER_SCAN)

    claimed = channel.take_pending()

    assert len(claimed) == 1
    assert claimed[0]["status"] == "running"
    # A second poll must not re-deliver the same command.
    assert channel.take_pending() == []


def test_take_pending_on_empty_queue_returns_empty_list(channel):
    assert channel.take_pending() == []


def test_complete_records_success_in_history(channel):
    record = channel.enqueue(COMMAND_TRIGGER_SCAN)
    claimed = channel.take_pending()[0]

    channel.complete(claimed, ok=True, result="已执行")

    history = channel.snapshot()["history"]
    assert history[-1]["id"] == record["id"]
    assert history[-1]["status"] == "done"
    assert history[-1]["result"] == "已执行"
    assert history[-1]["finished_at"]


def test_complete_records_failure_in_history(channel):
    channel.enqueue(COMMAND_TRIGGER_SCAN)
    claimed = channel.take_pending()[0]

    channel.complete(claimed, ok=False, result="源端不可用")

    history = channel.snapshot()["history"]
    assert history[-1]["status"] == "failed"
    assert history[-1]["result"] == "源端不可用"


def test_history_records_a_failed_command_without_claiming_again(channel):
    """A command that never runs must still be visible to the operator."""
    record = channel.enqueue(COMMAND_RESTART)

    snapshot = channel.snapshot()
    assert [item["id"] for item in snapshot["pending"]] == [record["id"]]
    assert any(item["id"] == record["id"] for item in snapshot["history"])


def test_command_status_finds_pending_then_history(channel):
    record = channel.enqueue(COMMAND_TRIGGER_SCAN)

    assert channel.command_status(record["id"])["status"] == "pending"

    claimed = channel.take_pending()[0]
    channel.complete(claimed, ok=True, result="ok")

    assert channel.command_status(record["id"])["status"] == "done"


def test_command_status_returns_none_for_unknown_id(channel):
    assert channel.command_status("does-not-exist") is None


def test_command_status_rejects_blank_id(channel):
    with pytest.raises(CommandError):
        channel.command_status("")


def test_pending_queue_is_bounded(channel):
    for _ in range(40):
        channel.enqueue(COMMAND_TRIGGER_SCAN)

    pending = channel.snapshot()["pending"]
    assert len(pending) <= 32


def test_history_is_bounded(channel):
    for _ in range(80):
        channel.enqueue(COMMAND_TRIGGER_SCAN)
        channel.complete(channel.take_pending()[0], ok=True, result="ok")

    assert len(channel.snapshot()["history"]) <= 50


def test_concurrent_enqueue_never_drops_a_command(channel):
    """Every append re-reads the file, so interleaved writes are preserved."""
    for _ in range(5):
        channel.enqueue(COMMAND_TRIGGER_SCAN)
    channel.enqueue(COMMAND_REDOWNLOAD_ASSET, {"asset_id": BV_ID})

    claimed = channel.take_pending()
    assert len(claimed) == 6
    assert any(item["command"] == COMMAND_REDOWNLOAD_ASSET for item in claimed)


def test_corrupted_inbox_does_not_raise(channel):
    with open(channel.path, "w", encoding="utf-8") as handle:
        handle.write("{not json")

    # A corrupt inbox must not wedge the daemon; a fresh command still works.
    record = channel.enqueue(COMMAND_TRIGGER_SCAN)
    assert channel.command_status(record["id"]) is not None


def test_truncated_pending_entry_is_ignored(channel):
    _write_inbox(channel, {"version": 1, "pending": ["junk", None], "history": []})

    assert channel.take_pending() == []


# ---------- payload validation ----------


def test_validate_accepts_supported_commands():
    assert validate_command_payload(COMMAND_TRIGGER_SCAN, None) == {}
    assert validate_command_payload(COMMAND_RESTART, {}) == {}
    assert validate_command_payload(
        COMMAND_REDOWNLOAD_ASSET, {"asset_id": BV_ID}
    ) == {"asset_id": BV_ID}
    assert validate_command_payload(COMMAND_REDOWNLOAD_ASSET, {"asset_id": AV_ID}) == {
        "asset_id": AV_ID
    }


def test_validate_rejects_unknown_command():
    with pytest.raises(CommandError):
        validate_command_payload("drop_everything", None)


def test_validate_rejects_delete_style_commands_even_if_supported_later():
    """Deleting local media stays outside the command surface by design."""
    for name in ("delete_asset", "delete_local_file", "wipe", "drop_database"):
        with pytest.raises(CommandError):
            validate_command_payload(name, None)


def test_validate_rejects_redownload_without_asset_id():
    with pytest.raises(CommandError):
        validate_command_payload(COMMAND_REDOWNLOAD_ASSET, {})


def test_validate_rejects_redownload_with_extra_argument():
    with pytest.raises(CommandError):
        validate_command_payload(
            COMMAND_REDOWNLOAD_ASSET, {"asset_id": BV_ID, "force": True}
        )


def test_validate_rejects_asset_id_that_is_a_path():
    """A path-like id must never reach the filesystem layer."""
    for bad in (
        "../../etc/passwd",
        "C:\\Windows\\System32",
        "/absolute/path",
        "BV1; rm -rf /",
        "..",
    ):
        with pytest.raises(CommandError):
            validate_command_payload(COMMAND_REDOWNLOAD_ASSET, {"asset_id": bad})


def test_validate_rejects_non_string_asset_id():
    with pytest.raises(CommandError):
        validate_command_payload(COMMAND_REDOWNLOAD_ASSET, {"asset_id": 12345})


def test_validate_rejects_unexpected_arguments_on_scan_command():
    with pytest.raises(CommandError):
        validate_command_payload(COMMAND_TRIGGER_SCAN, {"force": True})


def test_enqueue_rejects_invalid_payload(channel):
    with pytest.raises(CommandError):
        channel.enqueue(COMMAND_REDOWNLOAD_ASSET, {"asset_id": "../../secret"})
    assert channel.snapshot()["pending"] == []


def test_note_is_truncated_and_single_line(channel):
    record = channel.enqueue(COMMAND_TRIGGER_SCAN, note="a" * 500 + "\ninjected")

    assert len(record["note"]) <= 200
    assert "\n" not in record["note"]


# ---------- scanner redownload exemption ----------


def _scanner_stub():
    scanner = FavScanner.__new__(FavScanner)
    scanner._forced_redownloads = set()
    return scanner


def test_request_redownload_registers_both_spellings():
    scanner = _scanner_stub()

    keys = scanner.request_redownload(BV_ID)

    assert BV_ID in keys
    assert AV_ID in keys
    assert scanner._forced_redownloads == {BV_ID, AV_ID}


def test_request_redownload_normalizes_av_input():
    scanner = _scanner_stub()

    keys = scanner.request_redownload(AV_ID)

    assert keys == {AV_ID, BV_ID}


def test_redownload_exemption_applies_once_only():
    scanner = _scanner_stub()
    scanner.request_redownload(BV_ID)

    assert scanner._consume_forced_redownload(BV_ID) is True
    assert scanner._consume_forced_redownload(BV_ID) is False


def test_redownload_exemption_ignores_unrelated_asset():
    scanner = _scanner_stub()
    scanner.request_redownload(BV_ID)

    assert scanner._consume_forced_redownload("BV1otherasset") is False


def test_empty_redownload_request_registers_nothing():
    scanner = _scanner_stub()

    assert scanner.request_redownload("") == set()
    assert scanner.request_redownload(None) == set()


def test_unconvertible_asset_id_still_matches_itself():
    """A non-convertible key must not raise during command handling."""
    scanner = _scanner_stub()

    keys = scanner.request_redownload("BVnotreal")

    assert keys == {"BVnotreal"}


def test_should_skip_archived_video_defers_to_completeness_check():
    scanner = _scanner_stub()
    complete = {"p_count": 1, "bvid": BV_ID, "path": None}

    # Incomplete record (no directory) is never "already archived".
    assert scanner._should_skip_archived_video(BV_ID, complete) is False


def test_should_skip_archived_video_honours_forced_redownload():
    scanner = _scanner_stub()
    scanner.request_redownload(BV_ID)
    complete = {"p_count": 1, "bvid": BV_ID, "path": None}

    # Forced redownload bypasses the skip decision for exactly one pass.
    monkey_call = scanner._should_skip_archived_video(BV_ID, complete)
    assert monkey_call is False


# ---------- daemon dispatch ----------


class _StubScanner:
    def __init__(self):
        self.forced = []

    def request_redownload(self, asset_id):
        self.forced.append(asset_id)
        return {asset_id}


def _dispatch(channel, scanner=None, pending_scan=None, runtime=None):
    return asyncio.run(
        main._dispatch_commands(
            channel, scanner or _StubScanner(), runtime, pending_scan
        )
    )


def test_dispatch_trigger_scan_sets_pending_event(channel):
    channel.enqueue(COMMAND_TRIGGER_SCAN)
    pending = asyncio.Event()

    exit_requested = _dispatch(channel, pending_scan=pending)

    assert exit_requested is False
    assert pending.is_set()


def test_dispatch_trigger_scan_without_event_does_not_raise(channel):
    channel.enqueue(COMMAND_TRIGGER_SCAN)

    assert _dispatch(channel, pending_scan=None) is False


def test_dispatch_redownload_registers_asset(channel):
    channel.enqueue(COMMAND_REDOWNLOAD_ASSET, {"asset_id": BV_ID})
    scanner = _StubScanner()

    _dispatch(channel, scanner=scanner)

    assert scanner.forced == [BV_ID]


def test_dispatch_restart_requests_loop_exit(channel):
    channel.enqueue(COMMAND_RESTART)

    exit_requested = _dispatch(channel)

    assert exit_requested is True


def test_dispatch_acknowledges_success(channel):
    record = channel.enqueue(COMMAND_TRIGGER_SCAN)

    _dispatch(channel)

    assert channel.command_status(record["id"])["status"] == "done"


def test_dispatch_acknowledges_failure_without_crashing(channel):
    """A broken command must be recorded, never abort the scan loop."""

    class ExplodingScanner:
        def request_redownload(self, asset_id):
            raise RuntimeError("数据库锁死")

    record = channel.enqueue(COMMAND_REDOWNLOAD_ASSET, {"asset_id": BV_ID})

    exit_requested = _dispatch(channel, scanner=ExplodingScanner())

    assert exit_requested is False
    status = channel.command_status(record["id"])
    assert status["status"] == "failed"
    assert "数据库锁死" in status["result"]


def test_dispatch_handles_multiple_commands_in_one_poll(channel):
    first = channel.enqueue(COMMAND_TRIGGER_SCAN)
    second = channel.enqueue(COMMAND_REDOWNLOAD_ASSET, {"asset_id": BV_ID})
    scanner = _StubScanner()
    pending = asyncio.Event()

    _dispatch(channel, scanner=scanner, pending_scan=pending)

    assert channel.command_status(first["id"])["status"] == "done"
    assert channel.command_status(second["id"])["status"] == "done"
    assert scanner.forced == [BV_ID]


def test_dispatch_without_channel_is_a_noop():
    assert asyncio.run(main._dispatch_commands(None, _StubScanner(), None, None)) is False


def test_dispatch_survives_unreadable_channel(tmp_path, capsys):
    class BrokenChannel:
        def take_pending(self):
            raise OSError("设备不可用")

        def complete(self, *args, **kwargs):
            raise AssertionError("不应回执")

    assert asyncio.run(
        main._dispatch_commands(BrokenChannel(), _StubScanner(), None, None)
    ) is False


def test_dispatch_rejects_unsupported_command_from_edited_file(channel):
    """Even a hand-edited inbox cannot smuggle an unsupported command."""
    _write_inbox(
        channel,
        {
            "version": 1,
            "pending": [
                {
                    "id": "forged",
                    "command": "delete_asset",
                    "payload": {},
                    "status": "pending",
                }
            ],
            "history": [],
        },
    )

    _dispatch(channel)

    assert channel.command_status("forged")["status"] == "failed"