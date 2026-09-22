import json

from dandori import cli
from dandori.core import Ledger


def test_items_reports_children_ids_and_progress(ledger):
    parent = ledger.upsert({"ref": "vikunja:1", "title": "parent"}, source="s", actor="alice")
    result = ledger.split(parent["id"], ["child a", "child b"], actor="alice")
    child_a, child_b = result["children"]
    ledger.update(child_a["id"], status="done")

    items = {it["id"]: it for it in ledger.items()}
    parent_item = items[parent["id"]]
    assert set(parent_item["children"]) == {child_a["id"], child_b["id"]}
    assert parent_item["children_done"] == 1
    assert "children" not in items[child_a["id"]]


def test_orphan_part_of_gets_no_children_field(ledger):
    item = ledger.upsert(
        {"ref": "vikunja:1", "title": "solo", "deps": ["part-of:d-missing"]}, source="s", actor="alice",
    )
    items = ledger.items()
    assert len(items) == 1
    assert items[0]["id"] == item["id"]
    assert "children" not in items[0]


def test_cli_list_nests_children_with_progress_and_no_double_listing(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    ledger = Ledger(data_dir)
    parent = ledger.upsert({"ref": "vikunja:1", "title": "parent"}, source="s", actor="alice")
    ledger.split(parent["id"], ["child a", "child b"], actor="alice")

    assert cli.main(["list", "--dir", data_dir]) == 0
    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == 3
    parent_idx = next(i for i, l in enumerate(lines) if l.startswith(parent["id"]))
    assert "[0/2 done]" in lines[parent_idx]
    children_lines = lines[:parent_idx] + lines[parent_idx + 1:]
    assert all(l.startswith("  ") for l in children_lines)


def test_cli_list_orphan_part_of_falls_back_to_flat(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()
    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "solo",
              "--deps", "part-of:d-missing", "--source", "s"])
    capsys.readouterr()

    assert cli.main(["list", "--dir", data_dir]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert not lines[0].startswith(" ")


def test_cli_status_nests_children_across_states_under_parents_own_section(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    ledger = Ledger(data_dir, actor="alice")
    parent = ledger.upsert({"ref": "vikunja:1", "title": "epic"}, source="s", actor="alice")
    result = ledger.split(parent["id"], ["child a", "child b"], actor="alice")
    child_a, child_b = result["children"]
    ledger.claim(parent["id"], "alice")
    ledger.update(child_a["id"], status="done")

    assert cli.main(["status", "--dir", data_dir]) == 0
    lines = capsys.readouterr().out.splitlines()

    inflight_idx = lines.index("IN FLIGHT (1)")
    assert lines[inflight_idx + 1].strip().startswith(parent["id"])
    assert "[1/2 done]" in lines[inflight_idx + 1]
    nested = [lines[inflight_idx + 2], lines[inflight_idx + 3]]
    assert all(l.startswith("    ") for l in nested)
    assert any("(done)" in l for l in nested)
    assert any("(ready)" in l for l in nested)

    ready_idx = lines.index("READY (0)")
    assert lines[ready_idx + 1] == "WAITING (0)"


def test_cli_json_output_stays_flat_with_children_array(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    ledger = Ledger(data_dir)
    parent = ledger.upsert({"ref": "vikunja:1", "title": "parent"}, source="s", actor="alice")
    result = ledger.split(parent["id"], ["child a"], actor="alice")
    child = result["children"][0]

    assert cli.main(["list", "--dir", data_dir, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["data"]) == 2
    by_id = {it["id"]: it for it in payload["data"]}
    assert by_id[parent["id"]]["children"] == [child["id"]]
    assert "children" not in by_id[child["id"]]
