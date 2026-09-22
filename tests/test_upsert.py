def test_upsert_dedup_by_ref(ledger):
    a = ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:1", "title": "A changed"}, source="s", actor="alice")
    assert a["id"] == b["id"]
    assert len(ledger.items()) == 1
    assert b["title"] == "A changed"


def test_upsert_no_change_does_not_bump_updated(ledger):
    a = ledger.upsert({"ref": "vikunja:2", "title": "B"}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:2", "title": "B"}, source="s", actor="alice")
    assert a["updated"] == b["updated"]


def test_upsert_batch(ledger):
    items = ledger.upsert(
        [{"ref": "vikunja:3", "title": "C"}, {"ref": "vikunja:4", "title": "D"}],
        source="s", actor="alice",
    )
    assert len(items) == 2
    assert len(ledger.items()) == 2


def test_upsert_add_ref_merges_onto_existing_item(ledger):
    a = ledger.upsert({"ref": "vikunja:5", "title": "E"}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:5"}, source="s", actor="alice")
    assert a["id"] == b["id"]

    c = ledger.upsert({"refs": ["vikunja:5", "jira:5"]}, source="s", actor="alice")
    assert c["id"] == a["id"]
    assert "jira:5" in c["refs"]
    assert len(ledger.items()) == 1


def test_upsert_stamps_source_heartbeat(ledger):
    ledger.upsert({"ref": "vikunja:6", "title": "F"}, source="forgejo", actor="alice")
    sources = ledger.status()["sources"]
    assert "forgejo" in sources
    assert sources["forgejo"]["actor"] == "alice"


def test_id_keyed_upsert_does_not_pollute_refs(ledger):
    a = ledger.upsert({"ref": "vikunja:8", "title": "H"}, source="s", actor="alice")
    b = ledger.upsert({"refs": [a["id"], "jira:8"]}, source="s", actor="alice")
    assert b["id"] == a["id"]
    assert set(b["refs"]) == {"vikunja:8", "jira:8"}
    assert a["id"] not in b["refs"]


def test_upsert_status_change_writes_journal(ledger):
    a = ledger.upsert({"ref": "vikunja:7", "title": "G", "status": "ready"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:7", "status": "inflight"}, source="s", actor="alice")
    journal = ledger._read_journal()
    status_events = [e for e in journal if e["kind"] == "status" and e["ref"] == a["id"]]
    assert len(status_events) == 1
    assert "ready -> inflight" in status_events[0]["msg"]
