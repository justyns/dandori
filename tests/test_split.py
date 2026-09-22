def test_split_creates_children_and_needs_deps_on_parent(ledger):
    parent = ledger.upsert(
        {"ref": "forgejo:epic#1", "title": "epic", "project": "widgets"},
        source="s", actor="alice",
    )
    result = ledger.split(parent["id"], ["child a", "child b"], actor="alice")

    children = result["children"]
    assert [c["title"] for c in children] == ["child a", "child b"]
    for c in children:
        assert c["deps"] == [f"part-of:{parent['id']}"]
        assert c["project"] == "widgets"

    updated_parent = ledger.show(parent["id"])["item"]
    assert set(updated_parent["deps"]) == {f"needs:{c['id']}" for c in children}


def test_parent_blocked_until_all_children_done(ledger):
    parent = ledger.upsert({"ref": "vikunja:1", "title": "parent"}, source="s", actor="alice")
    result = ledger.split(parent["id"], ["child a", "child b"], actor="alice")
    child_a, child_b = result["children"]

    items = {i["id"]: i for i in ledger.items()}
    assert items[parent["id"]]["blocked"] is True

    ledger.update(child_a["id"], status="done")
    items = {i["id"]: i for i in ledger.items()}
    assert items[parent["id"]]["blocked"] is True

    ledger.update(child_b["id"], status="done")
    items = {i["id"]: i for i in ledger.items()}
    assert items[parent["id"]]["blocked"] is False


def test_part_of_never_blocks_children(ledger):
    parent = ledger.upsert({"ref": "vikunja:2", "title": "parent"}, source="s", actor="alice")
    result = ledger.split(parent["id"], ["child a"], actor="alice")
    child = result["children"][0]

    items = {i["id"]: i for i in ledger.items()}
    assert items[child["id"]]["blocked"] is False


def test_children_claimable_independently(ledger):
    parent = ledger.upsert({"ref": "vikunja:3", "title": "parent"}, source="s", actor="alice")
    result = ledger.split(parent["id"], ["child a", "child b"], actor="alice")
    child_a, child_b = result["children"]

    claimed_a = ledger.claim(child_a["id"], "alice")
    claimed_b = ledger.claim(child_b["id"], "bob")
    assert claimed_a["claimed_by"] == "alice"
    assert claimed_b["claimed_by"] == "bob"


def test_show_lists_children_via_part_of_back_references(ledger):
    parent = ledger.upsert({"ref": "vikunja:4", "title": "parent"}, source="s", actor="alice")
    result = ledger.split(parent["id"], ["child a"], actor="alice")
    child = result["children"][0]
    ledger.claim(child["id"], "alice")

    shown = ledger.show(parent["id"])
    assert len(shown["children"]) == 1
    assert shown["children"][0]["id"] == child["id"]
    assert shown["children"][0]["claimed_by"] == "alice"
