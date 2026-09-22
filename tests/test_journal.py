from datetime import datetime, timezone


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
