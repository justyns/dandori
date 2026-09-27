from datetime import datetime, timezone

import pytest

from dandori.core import ItemNotFoundError


def test_journal_file_named_per_host_month(ledger):
    ledger.log("hello", actor="alice")
    now = datetime.now(timezone.utc)
    expected = ledger.journal_dir / f"testhost-{now:%Y-%m}.jsonl"
    assert expected.exists()


def test_journal_readers_merge_sort_across_host_files(ledger):
    ledger.journal_dir.mkdir(parents=True, exist_ok=True)
    other_path = ledger.journal_dir / "otherhost-2026-01.jsonl"
    other_path.write_text(
        '{"ts": "2026-01-01T00:00:00Z", "host": "otherhost", "actor": "bob", '
        '"kind": "log", "msg": "from another host", "ref": null}\n'
    )
    ledger.log("from this host", actor="alice")
    entries = ledger._read_journal()
    assert [e["host"] for e in entries] == ["otherhost", "testhost"]


def test_log_resolves_an_external_ref_to_the_item_id(ledger):
    item = ledger.upsert({"ref": "jira:X-123", "title": "T"}, source="s", actor="alice")
    entry = ledger.log("note", ref="jira:X-123", actor="alice")
    assert entry["ref"] == item["id"]
    assert ledger.show(item["id"])["journal"][-1]["msg"] == "note"


def test_log_refuses_a_ref_that_matches_no_item(ledger):
    with pytest.raises(ItemNotFoundError):
        ledger.log("note", ref="jira:TYPO-1", actor="alice")
    assert not any(e["kind"] == "log" for e in ledger._read_journal())


def test_doctor_reports_orphaned_log_refs_as_informational(ledger):
    ledger.journal_dir.mkdir(parents=True, exist_ok=True)
    (ledger.journal_dir / "otherhost-2026-01.jsonl").write_text(
        '{"ts": "2026-01-01T00:00:00Z", "host": "otherhost", "actor": "bob", '
        '"kind": "log", "msg": "old", "ref": "jira:BLAH-123"}\n'
    )
    result = ledger.doctor()
    orphaned = [p for p in result["problems"] if p["check"] == "orphaned_log_ref"]
    assert [(p["ref"], p["severity"]) for p in orphaned] == [("jira:BLAH-123", "info")]
    assert result["has_errors"] is False
