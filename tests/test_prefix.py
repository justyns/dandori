import pytest

from dandori.core import DandoriError, load_config


def test_fresh_init_seeds_default_prefixes(ledger):
    prefixes = load_config(ledger.data_dir)["prefixes"]
    assert prefixes["vikunja"]["kind"] == "ref"
    assert prefixes["jira"]["kind"] == "ref"
    assert prefixes["commit"]["kind"] == "link"
    assert prefixes["pr"]["kind"] == "link"


def test_upsert_refuses_unregistered_ref_prefix_listing_registered_ones(ledger):
    with pytest.raises(DandoriError) as exc:
        ledger.upsert({"ref": "totallymadeup:1", "title": "A"}, source="s", actor="alice")
    assert "totallymadeup" in str(exc.value)
    assert "vikunja" in str(exc.value)


def test_prefix_add_and_list(ledger):
    ledger.prefix_add("acme", "ref", desc="Acme tracker", actor="alice")
    listed = {p["name"]: p for p in ledger.prefix_list()}
    assert listed["acme"] == {"name": "acme", "kind": "ref", "desc": "Acme tracker"}


def test_doctor_flags_unregistered_prefix_on_grandfathered_item(ledger):
    item = ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    path = ledger.items_dir / f"{item['id']}.md"
    text = path.read_text(encoding="utf-8").replace("vikunja:1", "legacysystem:1")
    path.write_text(text, encoding="utf-8")

    result = ledger.doctor()
    assert result["clean"] is False
    unreg = [p for p in result["problems"] if p["check"] == "unregistered_prefix"]
    assert len(unreg) == 1
    assert unreg[0]["value"] == "legacysystem:1"


def test_prefix_add_invalid_kind_rejected(ledger):
    with pytest.raises(DandoriError):
        ledger.prefix_add("acme", "bogus")
