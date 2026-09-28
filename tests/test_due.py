import pytest

from dandori.core import DandoriError


def test_upsert_rejects_garbage_due(ledger):
    with pytest.raises(DandoriError, match="due date"):
        ledger.upsert({"ref": "vikunja:1", "title": "T", "due": "not-a-date"}, source="s", actor="alice")


def test_update_sets_and_clears_due(ledger):
    item = ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    updated = ledger.update(item["id"], due="2026-02-01", actor="alice")
    assert updated["due"] == "2026-02-01"
    cleared = ledger.update(item["id"], due="", actor="alice")
    assert "due" not in cleared


def test_update_rejects_garbage_due(ledger):
    item = ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    with pytest.raises(DandoriError, match="due date"):
        ledger.update(item["id"], due="15-01-2026", actor="alice")


def test_status_overdue_section_excludes_done_parked_idea(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "overdue ready", "due": "2020-01-01"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:2", "title": "overdue done", "due": "2020-01-01", "status": "done"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:3", "title": "overdue parked", "due": "2020-01-01", "status": "parked"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:4", "title": "overdue idea", "due": "2020-01-01", "status": "idea"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:5", "title": "future", "due": "2099-01-01"}, source="s", actor="alice")

    result = ledger.status()
    overdue_titles = {it["title"] for it in result["overdue"]}
    assert overdue_titles == {"overdue ready"}


def test_status_ready_sorts_by_due_then_priority(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "no due, p1", "priority": 1}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:2", "title": "due later", "due": "2026-06-01", "priority": 2}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:3", "title": "due sooner", "due": "2026-01-01", "priority": 4}, source="s", actor="alice")

    result = ledger.status()
    titles = [it["title"] for it in result["sections"]["ready"]]
    assert titles == ["due sooner", "due later", "no due, p1"]

