import io
import json
import sys

from dandori import cli
from dandori.core import Ledger, parse_item_file, render_item_file


def test_upsert_comma_string_tags_split_into_a_list(ledger):
    result = ledger.upsert({"title": "T", "tags": "a,b", "status": "idea"}, source="s", actor="alice")
    assert result["tags"] == ["a", "b"]


def test_upsert_list_tags_unaffected(ledger):
    result = ledger.upsert({"title": "T", "tags": ["a", "b"], "status": "idea"}, source="s", actor="alice")
    assert result["tags"] == ["a", "b"]


def test_upsert_comma_string_deps_split_into_a_list(ledger):
    result = ledger.upsert({"title": "T", "deps": "needs:x,needs:y"}, source="s", actor="alice")
    assert result["deps"] == ["needs:x", "needs:y"]


def test_upsert_comma_string_links_split_into_a_list(ledger):
    result = ledger.upsert({"title": "T", "links": "commit:aaa,commit:bbb"}, source="s", actor="alice")
    assert result["links"] == ["commit:aaa", "commit:bbb"]


def test_upsert_single_string_ref_is_not_comma_split(ledger):
    """A ref is one whole value (dori upsert --ref is repeatable, never
    comma-joined) -- unlike tags/deps/links it must not be split."""
    result = ledger.upsert({"title": "T", "refs": "vikunja:1"}, source="s", actor="alice")
    assert result["refs"] == ["vikunja:1"]


def test_upsert_updating_existing_item_also_splits_string_tags(ledger):
    a = ledger.upsert({"ref": "vikunja:9", "title": "T", "tags": ["x"]}, source="s", actor="alice")
    b = ledger.upsert({"ref": "vikunja:9", "tags": "a,b"}, source="s", actor="alice")
    assert a["id"] == b["id"]
    assert b["tags"] == ["a", "b"]


def test_cli_upsert_stdin_json_tags_string_does_not_iterate_per_character(tmp_path, capsys, monkeypatch):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    payload = json.dumps([{"title": "dori tags probe", "tags": "a,b", "status": "idea"}])
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    rc = cli.main(["upsert", "--dir", data_dir, "--stdin-json", "--source", "s", "--actor", "alice"])
    assert rc == 0

    item_id = next((tmp_path / "data" / "items").glob("*.md")).stem
    result = Ledger(data_dir).show(item_id)
    assert result["item"]["tags"] == ["a", "b"]


def test_doctor_reports_string_tags_without_rewriting_the_item(ledger):
    item = ledger.upsert({"title": "T", "status": "idea"}, source="s", actor="alice")
    path = ledger.items_dir / f"{item['id']}.md"
    fm, body = parse_item_file(path)
    fm["tags"] = "a,b"
    path.write_text(render_item_file(fm, body))

    result = ledger.doctor()
    assert result["clean"] is False
    assert any(p["check"] == "string_tags" and p["item"] == item["id"] for p in result["problems"])

    fm_after, _ = parse_item_file(path)
    assert fm_after["tags"] == "a,b"


def test_doctor_clean_when_tags_is_a_list(ledger):
    ledger.upsert({"title": "T", "tags": ["a", "b"]}, source="s", actor="alice")
    result = ledger.doctor()
    assert not any(p["check"] == "string_tags" for p in result["problems"])
