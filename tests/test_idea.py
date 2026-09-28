def test_idea_excluded_from_status_sections(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "idea one", "status": "idea"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:2", "title": "ready one", "status": "ready"}, source="s", actor="alice")

    status = ledger.status()
    all_titles = [it["title"] for items in status["sections"].values() for it in items]
    assert "idea one" not in all_titles
    assert "ready one" in all_titles


def test_idea_can_be_claimed(ledger):
    item = ledger.upsert({"ref": "vikunja:3", "title": "idea two", "status": "idea"}, source="s", actor="alice")
    result = ledger.claim(item["id"], "alice")
    assert result["claimed_by"] == "alice"
    assert result["status"] == "idea"


def test_release_resumes_hidden_ness_for_an_idea(ledger):
    item = ledger.upsert({"ref": "vikunja:3c", "title": "idea two-c", "status": "idea"}, source="s", actor="alice")
    ledger.claim(item["id"], "alice")
    ledger.release(item["id"], "alice")

    status = ledger.status()
    all_titles = [it["title"] for items in status["sections"].values() for it in items]
    assert "idea two-c" not in all_titles


def test_update_allows_status_idea_on_a_claimed_item(ledger):
    item = ledger.upsert({"ref": "vikunja:4", "title": "idea three"}, source="s", actor="alice")
    ledger.claim(item["id"], "alice")

    ledger.update(item["id"], status="idea")

    reloaded = ledger.show(item["id"])["item"]
    assert reloaded["status"] == "idea"
    assert reloaded["claimed_by"] == "alice"
