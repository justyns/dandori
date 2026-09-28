import json
import subprocess

import pytest

from dandori import cli
from dandori.core import DandoriError, Ledger, parse_item_file, render_item_file


def test_status_json_envelope(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    assert cli.main(["init", "--dir", data_dir]) == 0
    capsys.readouterr()

    assert cli.main(["status", "--dir", data_dir, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert set(payload["data"].keys()) == {"sources", "overdue", "sections"}
    assert set(payload["data"]["sections"]) == {"in_flight", "ready", "waiting"}


def test_claim_without_actor_fails_with_nonzero_exit(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "T", "--source", "s"])
    capsys.readouterr()

    rc = cli.main(["claim", "d-doesnotmatter", "--dir", data_dir])
    assert rc != 0
    assert "actor" in capsys.readouterr().err


def test_dori_dir_env_var_selects_data_dir(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    monkeypatch.setenv("DORI_DIR", data_dir)
    assert cli.main(["init"]) == 0
    assert (tmp_path / "data" / "config.yaml").exists()


def test_dir_flag_wins_over_dori_dir_env_var(tmp_path, capsys, monkeypatch):
    env_dir = str(tmp_path / "env-data")
    flag_dir = str(tmp_path / "flag-data")
    monkeypatch.setenv("DORI_DIR", env_dir)
    assert cli.main(["init", "--dir", flag_dir]) == 0
    capsys.readouterr()

    assert not (tmp_path / "env-data" / "config.yaml").exists()
    assert (tmp_path / "flag-data" / "config.yaml").exists()


def test_upsert_project_flag_and_list_filter(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "T",
              "--project", "widgets", "--source", "s"])
    capsys.readouterr()

    assert cli.main(["list", "--dir", data_dir, "--project", "widgets", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["data"]) == 1
    assert payload["data"][0]["project"] == "widgets"

    assert cli.main(["list", "--dir", data_dir, "--project", "other", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == []


def test_doctor_command_exit_codes(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "T", "--source", "s"])
    capsys.readouterr()

    assert cli.main(["doctor", "--dir", data_dir, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == {"problems": [], "clean": True, "has_errors": False}

    ledger = Ledger(data_dir)
    dup_id = ledger.upsert({"ref": "vikunja:2", "title": "U"}, source="s", actor="alice")["id"]
    path = ledger.items_dir / f"{dup_id}.md"
    fm, body = parse_item_file(path)
    fm["refs"] = ["vikunja:1"]
    path.write_text(render_item_file(fm, body), encoding="utf-8")

    assert cli.main(["doctor", "--dir", data_dir]) == 1


def test_doctor_command_exits_0_for_informational_only_findings(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    ledger = Ledger(data_dir)
    item = ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    ledger.claim(item["id"], "alice")
    path = ledger.items_dir / f"{item['id']}.md"
    fm, body = parse_item_file(path)
    fm["claimed_at"] = "2020-01-01T00:00:00Z"
    path.write_text(render_item_file(fm, body), encoding="utf-8")
    capsys.readouterr()

    rc = cli.main(["doctor", "--dir", data_dir, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["problems"]
    assert payload["data"]["clean"] is False
    assert payload["data"]["has_errors"] is False
    assert rc == 0


def test_split_command(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "parent", "--source", "s"])
    capsys.readouterr()

    assert cli.main(["split", "d-doesnotmatter", "some title", "--dir", data_dir]) != 0
    capsys.readouterr()

    assert cli.main(["list", "--dir", data_dir, "--json"]) == 0
    parent_id = json.loads(capsys.readouterr().out)["data"][0]["id"]

    assert cli.main(["split", parent_id, "child a", "child b", "--dir", data_dir, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["data"]["children"]) == 2


def _init_with_item(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "T",
              "--source", "s", "--actor", "alice"])
    capsys.readouterr()
    return data_dir, Ledger(data_dir).items()[0]["id"]


def test_cli_claim_release_update_and_show_journal(tmp_path, capsys):
    data_dir, item_id = _init_with_item(tmp_path, capsys)
    assert cli.main(["claim", item_id, "--dir", data_dir, "--actor", "alice"]) == 0
    capsys.readouterr()
    assert cli.main(["release", item_id, "--dir", data_dir, "--actor", "alice"]) == 0
    assert capsys.readouterr().out.strip() == f"released {item_id}"
    assert cli.main(["update", item_id, "--dir", data_dir, "--status", "done", "--actor", "alice"]) == 0
    assert "(task, p2)" in capsys.readouterr().out
    assert cli.main(["show", item_id, "--dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "[status] status: ready -> done" in out


def test_cli_update_no_project_clears_it(tmp_path, capsys):
    data_dir, item_id = _init_with_item(tmp_path, capsys)
    assert cli.main(["update", item_id, "--dir", data_dir, "--no-project", "--actor", "alice"]) == 0
    capsys.readouterr()
    assert cli.main(["list", "--dir", data_dir, "--json"]) == 0
    assert "project" not in json.loads(capsys.readouterr().out)["data"][0]


def test_cli_status_prints_overdue_section(tmp_path, capsys):
    data_dir, item_id = _init_with_item(tmp_path, capsys)
    cli.main(["update", item_id, "--dir", data_dir, "--due", "2020-01-01", "--actor", "alice"])
    capsys.readouterr()
    assert cli.main(["status", "--dir", data_dir]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[lines.index("OVERDUE (1)") + 1].strip().startswith(item_id)


def test_cli_prefix_add_and_list(tmp_path, capsys):
    data_dir, _ = _init_with_item(tmp_path, capsys)
    assert cli.main(["prefix", "add", "acme", "--kind", "both", "--desc", "Acme", "--dir", data_dir]) == 0
    assert cli.main(["prefix", "list", "--dir", data_dir]) == 0
    assert "acme  both  Acme" in capsys.readouterr().out


def test_cli_sync_to_bare_origin(tmp_path, capsys):
    data_dir, _ = _init_with_item(tmp_path, capsys)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=data_dir, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=data_dir, check=True, capture_output=True)
    assert cli.main(["sync", "--dir", data_dir]) == 0
    assert capsys.readouterr().out.strip() == "pushed initial commit to empty origin"


def test_commands_refuse_a_dir_that_is_not_a_ledger(tmp_path, capsys):
    assert cli.main(["status", "--dir", str(tmp_path / "nope")]) == 1
    assert "not a dandori ledger" in capsys.readouterr().err
    with pytest.raises(DandoriError, match="not a dandori ledger"):
        Ledger(tmp_path / "nope").log("x", actor="alice")
