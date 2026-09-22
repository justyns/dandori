def test_blocked_derived_from_open_dep(ledger):
    dep = ledger.upsert({"ref": "vikunja:10", "title": "dep", "status": "ready"}, source="s", actor="alice")
    item = ledger.upsert(
        {"ref": "vikunja:11", "title": "blocked", "deps": [f"blocks:{dep['id']}"]},
        source="s", actor="alice",
    )

    items = {i["id"]: i for i in ledger.items()}
    assert items[item["id"]]["blocked"] is True
    assert items[item["id"]]["blocked_by"] == [dep["id"]]
    assert items[dep["id"]]["blocked"] is False

    ledger.update(dep["id"], status="done")

    items = {i["id"]: i for i in ledger.items()}
    assert items[item["id"]]["blocked"] is False
    assert items[item["id"]]["blocked_by"] == []
