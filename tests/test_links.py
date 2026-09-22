def test_link_may_repeat_across_items(ledger):
    link = "pr:forgejo:tsugite#900"
    a = ledger.upsert({"ref": "vikunja:1", "title": "A", "links": [link]}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:2", "title": "B", "links": [link]}, source="s", actor="alice")
    assert a["links"] == [link]
    assert b["links"] == [link]
