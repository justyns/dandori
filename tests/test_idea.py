import pytest

from dandori.core import DandoriError, parse_item_file, render_item_file


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


def test_update_refuses_idea_on_a_claimed_item(ledger):
    item = ledger.upsert({"ref": "vikunja:4", "title": "idea three"}, source="s", actor="alice")
    ledger.claim(item["id"], "alice")

    with pytest.raises(DandoriError) as exc:
        ledger.update(item["id"], status="idea")
    assert "release" in str(exc.value)

    reloaded = ledger.show(item["id"])["item"]
    assert reloaded["status"] == "inflight"
    assert reloaded["claimed_by"] == "alice"


def test_doctor_flags_a_claimed_idea_item(ledger):
    item = ledger.upsert({"ref": "vikunja:5", "title": "idea four"}, source="s", actor="alice")
    ledger.claim(item["id"], "alice")
    path = ledger.items_dir / f"{item['id']}.md"
    fm, body = parse_item_file(path)
    fm["status"] = "idea"
    path.write_text(render_item_file(fm, body), encoding="utf-8")

    result = ledger.doctor()
    assert result["clean"] is False
    claimed_idea = [p for p in result["problems"] if p["check"] == "claimed_idea"]
    assert len(claimed_idea) == 1
    assert claimed_idea[0]["item"] == item["id"]
    assert claimed_idea[0]["severity"] == "error"
    assert result["has_errors"] is True


def test_upsert_refuses_idea_on_a_claimed_item(ledger):
    item = ledger.upsert({"ref": "vikunja:6", "title": "idea five"}, source="s", actor="alice")
    ledger.claim(item["id"], "alice")

    with pytest.raises(DandoriError):
        ledger.upsert({"ref": "vikunja:6", "status": "idea"}, source="s", actor="alice")
    assert ledger.show(item["id"])["item"]["status"] == "inflight"
