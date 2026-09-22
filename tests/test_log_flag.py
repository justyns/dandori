def _make_item(ledger, ref="jira:1"):
    return ledger.upsert({"ref": ref, "title": "t"}, source="test", actor="alice")


def test_update_log_journals_adjacent_to_status_change(ledger):
    item = _make_item(ledger)
    ledger.update(item["id"], status="done", log="I did the thing", actor="alice")
    events = ledger.show(item["id"])["journal"]
    kinds = [e["kind"] for e in events]
    idx = kinds.index("status")
    assert kinds[idx + 1] == "log"
    assert events[idx + 1]["msg"] == "I did the thing"


def test_update_log_with_other_field_but_no_status_is_fine(ledger):
    item = _make_item(ledger)
    result = ledger.update(item["id"], priority=1, log="bumping priority", actor="alice")
    assert result["priority"] == 1
    journal = ledger._read_journal()
    assert any(e["kind"] == "log" and e["msg"] == "bumping priority" for e in journal)


def test_claim_log_journals_adjacent_to_claim(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice", log="starting work")
    events = ledger.show(item["id"])["journal"]
    kinds_msgs = [(e["kind"], e["msg"]) for e in events]
    assert ("claim", "claimed by alice") in kinds_msgs
    assert kinds_msgs[-1] == ("log", "starting work")


def test_release_log_journals_adjacent_to_release(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    ledger.release(item["id"], "alice", log="handing it off")
    events = ledger.show(item["id"])["journal"]
    kinds_msgs = [(e["kind"], e["msg"]) for e in events]
    assert ("release", "released by alice") in kinds_msgs
    assert kinds_msgs[-1] == ("log", "handing it off")
