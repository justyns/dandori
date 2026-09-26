import pytest

from dandori.core import RefConflictError, parse_item_file, render_item_file


def test_add_ref_refuses_ref_already_held_by_another_item(ledger):
    a = ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:2", "title": "B"}, source="s", actor="alice")

    with pytest.raises(RefConflictError) as exc:
        ledger.upsert({"refs": ["vikunja:2", "vikunja:1"]}, source="s", actor="alice")
    assert a["id"] in str(exc.value)

    assert ledger.show(a["id"])["item"]["refs"] == ["vikunja:1"]
    assert ledger.show(b["id"])["item"]["refs"] == ["vikunja:2"]


def test_ambiguous_ref_lookup_picks_oldest_and_warns(ledger):
    a = ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:2", "title": "B"}, source="s", actor="alice")

    path_a = ledger.items_dir / f"{a['id']}.md"
    fm_a, body_a = parse_item_file(path_a)
    fm_a["created"] = "2020-01-01T00:00:00Z"
    path_a.write_text(render_item_file(fm_a, body_a), encoding="utf-8")

    path_b = ledger.items_dir / f"{b['id']}.md"
    fm_b, body_b = parse_item_file(path_b)
    fm_b["refs"] = ["vikunja:1"]
    path_b.write_text(render_item_file(fm_b, body_b), encoding="utf-8")

    result = ledger.show("vikunja:1")
    assert result["item"]["id"] == a["id"]
    assert a["id"] in result["ref_warning"]
    assert b["id"] in result["ref_warning"]


def test_doctor_finds_duplicate_ref_from_hand_crafted_merge(ledger):
    a = ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:2", "title": "B"}, source="s", actor="alice")

    path_b = ledger.items_dir / f"{b['id']}.md"
    fm, body = parse_item_file(path_b)
    fm["refs"] = ["vikunja:1"]
    path_b.write_text(render_item_file(fm, body), encoding="utf-8")

    result = ledger.doctor()
    assert result["clean"] is False
    dup = [p for p in result["problems"] if p["check"] == "duplicate_ref"]
    assert len(dup) == 1
    assert dup[0]["ref"] == "vikunja:1"
    assert set(dup[0]["items"]) == {a["id"], b["id"]}


def test_doctor_detects_dangling_dep(ledger):
    item = ledger.upsert(
        {"ref": "vikunja:1", "title": "A", "deps": ["needs:d-missing"]}, source="s", actor="alice",
    )
    result = ledger.doctor()
    assert result["clean"] is False
    dangling = [p for p in result["problems"] if p["check"] == "dangling_dep"]
    assert dangling == [{
        "check": "dangling_dep", "severity": "error", "item": item["id"], "dep": "needs:d-missing",
        "message": f"{item['id']} has needs:d-missing but d-missing does not exist",
    }]


def test_doctor_does_not_flag_valid_split_deps(ledger):
    parent = ledger.upsert({"ref": "vikunja:1", "title": "parent"}, source="s", actor="alice")
    ledger.split(parent["id"], ["child a"], actor="alice")
    assert ledger.doctor()["clean"] is True


def test_doctor_reports_expired_claim_as_informational(ledger):
    item = ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    ledger.claim(item["id"], "alice")
    path = ledger.items_dir / f"{item['id']}.md"
    fm, body = parse_item_file(path)
    fm["claimed_at"] = "2020-01-01T00:00:00Z"
    path.write_text(render_item_file(fm, body), encoding="utf-8")

    result = ledger.doctor()
    expired = [p for p in result["problems"] if p["check"] == "expired_claim"]
    assert len(expired) == 1
    assert expired[0]["item"] == item["id"]
    assert expired[0]["severity"] == "info"
    assert result["has_errors"] is False
