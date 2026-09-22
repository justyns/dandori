import pytest

from dandori.core import DandoriError


def test_idea_excluded_from_status_sections(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "idea one", "status": "idea"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:2", "title": "ready one", "status": "ready"}, source="s", actor="alice")

    status = ledger.status()
    all_titles = [it["title"] for bucket in ("inflight", "ready", "waiting") for it in status[bucket]]
    assert "idea one" not in all_titles
    assert "ready one" in all_titles


def test_idea_cannot_be_claimed(ledger):
    item = ledger.upsert({"ref": "vikunja:3", "title": "idea two", "status": "idea"}, source="s", actor="alice")
    with pytest.raises(DandoriError):
        ledger.claim(item["id"], "alice")

