import dandori.core as core


def test_batch_upsert_parses_each_item_file_once(ledger, monkeypatch):
    n = 50
    ledger.upsert([{"ref": f"vikunja:{i}", "title": f"item {i}"} for i in range(n)], source="s", actor="alice")

    calls = 0
    parse = core.parse_item_file

    def counting_parse(path):
        nonlocal calls
        calls += 1
        return parse(path)

    monkeypatch.setattr(core, "parse_item_file", counting_parse)
    results = ledger.upsert([{"ref": f"vikunja:{i}", "title": f"item {i} v2"} for i in range(n)],
                            source="s", actor="alice")

    assert all(r["title"].endswith("v2") for r in results)
    assert calls == n
