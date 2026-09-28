from datetime import datetime, timedelta, timezone

import pytest

from dandori import cli
from dandori.core import DEFAULT_STATUSES, DandoriError, load_config, parse_item_file, render_item_file, save_config


def _edit_config(ledger, change):
    config = load_config(ledger.data_dir)
    change(config)
    save_config(ledger.data_dir, config)


def _backdate(ledger, item_id, **fields):
    path = ledger.items_dir / f"{item_id}.md"
    fm, body = parse_item_file(path)
    fm.update(fields)
    path.write_text(render_item_file(fm, body), encoding="utf-8")


def _rename_done_to_finished(config):
    config["statuses"]["finished"] = config["statuses"].pop("done")


def test_init_seeds_default_statuses(ledger):
    config = load_config(ledger.data_dir)
    assert config["statuses"] == DEFAULT_STATUSES
    assert config["default_status"] == "ready"


def test_writes_and_filters_refuse_an_unregistered_status(ledger):
    with pytest.raises(DandoriError) as exc:
        ledger.upsert({"ref": "vikunja:1", "title": "A", "status": "bogus"}, source="s", actor="alice")
    assert "bogus" in str(exc.value) and "ready" in str(exc.value)

    item = ledger.upsert({"ref": "vikunja:2", "title": "A"}, source="s", actor="alice")
    with pytest.raises(DandoriError, match="bogus"):
        ledger.update(item["id"], status="bogus")
    with pytest.raises(DandoriError, match="not registered"):
        ledger.items(status="bogus")


def test_cli_passes_any_status_string_to_the_ledger(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    rc = cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "T",
                   "--status", "bogus", "--source", "s"])
    assert rc == 1
    assert "bogus" in capsys.readouterr().err


def test_upsert_and_split_use_the_configured_default_status(ledger):
    _edit_config(ledger, lambda c: c.update(default_status="waiting"))

    parent = ledger.upsert({"ref": "vikunja:3", "title": "parent"}, source="s", actor="alice")
    assert parent["status"] == "waiting"
    assert ledger.split(parent["id"], ["child a"], actor="alice")["children"][0]["status"] == "waiting"


def test_an_unregistered_default_status_refuses_the_write(ledger):
    _edit_config(ledger, lambda c: c.update(default_status="bogus"))

    with pytest.raises(DandoriError, match="bogus"):
        ledger.upsert({"ref": "vikunja:4", "title": "A"}, source="s", actor="alice")
    assert ledger.items() == []


def test_a_missing_statuses_map_fails_reads_and_writes(ledger):
    ledger.upsert({"ref": "vikunja:5", "title": "A"}, source="s", actor="alice")
    _edit_config(ledger, lambda c: c.pop("statuses"))

    with pytest.raises(DandoriError, match="no statuses map"):
        ledger.status()
    with pytest.raises(DandoriError, match="no statuses map"):
        ledger.upsert({"ref": "vikunja:6", "title": "B", "status": "ready"}, source="s", actor="alice")


def test_a_status_missing_a_flag_fails_loudly(ledger):
    _edit_config(ledger, lambda c: c["statuses"]["waiting"].pop("section"))

    with pytest.raises(DandoriError, match="'waiting' in config.yaml is missing section"):
        ledger.status()


def test_blocked_is_reserved_even_if_added_to_config(ledger):
    _edit_config(ledger, lambda c: c["statuses"].update(
        blocked={"section": "ready", "stale_days": None, "terminal": False}))

    with pytest.raises(DandoriError, match="reserved"):
        ledger.upsert({"ref": "vikunja:7", "title": "A", "status": "blocked"}, source="s", actor="alice")


def test_blocked_and_children_done_follow_the_terminal_flag_not_the_name(ledger):
    _edit_config(ledger, _rename_done_to_finished)

    dep = ledger.upsert({"ref": "vikunja:8", "title": "dep"}, source="s", actor="alice")
    item = ledger.upsert(
        {"ref": "vikunja:9", "title": "blocked", "deps": [f"blocks:{dep['id']}"]}, source="s", actor="alice",
    )
    assert {i["id"]: i for i in ledger.items()}[item["id"]]["blocked"] is True

    ledger.update(dep["id"], status="finished")
    assert {i["id"]: i for i in ledger.items()}[item["id"]]["blocked"] is False


def test_overdue_and_sections_follow_the_flags_not_the_name(ledger):
    _edit_config(ledger, _rename_done_to_finished)

    ledger.upsert({"ref": "vikunja:10", "title": "finished overdue", "due": "2020-01-01", "status": "finished"},
                  source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:11", "title": "ready overdue", "due": "2020-01-01"}, source="s", actor="alice")

    status = ledger.status()
    assert {it["title"] for it in status["overdue"]} == {"ready overdue"}
    assert "finished overdue" not in [it["title"] for items in status["sections"].values() for it in items]


def test_a_custom_section_renders_and_cannot_shadow_overdue(ledger):
    _edit_config(ledger, lambda c: c["statuses"].update(
        review={"section": "overdue", "stale_days": None, "terminal": False}))

    ledger.upsert({"ref": "vikunja:12", "title": "in review", "status": "review"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:13", "title": "late", "due": "2020-01-01"}, source="s", actor="alice")

    status = ledger.status()
    assert [it["title"] for it in status["sections"]["overdue"]] == ["in review"]
    assert [it["title"] for it in status["overdue"]] == ["late"]


def test_a_claim_shows_the_item_in_flight_unless_its_status_is_terminal(ledger):
    idea = ledger.upsert({"ref": "vikunja:14", "title": "idea", "status": "idea"}, source="s", actor="alice")
    finished = ledger.upsert({"ref": "vikunja:15", "title": "finished"}, source="s", actor="alice")
    ledger.claim(idea["id"], "alice", sync=False)
    ledger.claim(finished["id"], "alice", sync=False)
    ledger.update(finished["id"], status="done")

    sections = ledger.status()["sections"]
    assert [it["title"] for it in sections["in_flight"]] == ["idea"]
    assert "finished" not in [it["title"] for items in sections.values() for it in items]


def test_doctor_reports_unregistered_statuses_as_informational(ledger):
    item = ledger.upsert({"ref": "vikunja:16", "title": "T"}, source="s", actor="alice")
    _backdate(ledger, item["id"], status="legacystatus")

    result = ledger.doctor()
    unreg = [p for p in result["problems"] if p["check"] == "unregistered_status"]
    assert [(p["item"], p["severity"]) for p in unreg] == [(item["id"], "info")]
    assert result["has_errors"] is False


def test_doctor_reports_stale_items_only_for_statuses_with_stale_days(ledger):
    _edit_config(ledger, lambda c: c["statuses"]["waiting"].update(stale_days=3))
    old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stuck = ledger.upsert({"ref": "vikunja:17", "title": "stuck", "status": "waiting"}, source="s", actor="alice")
    fine = ledger.upsert({"ref": "vikunja:18", "title": "fine"}, source="s", actor="alice")
    _backdate(ledger, stuck["id"], updated=old)
    _backdate(ledger, fine["id"], updated=old)

    stale = [p for p in ledger.doctor()["problems"] if p["check"] == "stale_item"]
    assert [(p["item"], p["severity"]) for p in stale] == [(stuck["id"], "info")]


def test_guide_lists_statuses_and_default_status(ledger):
    data = ledger.guide()
    assert data["default_status"] == "ready"
    assert {s["name"] for s in data["statuses"]} == set(DEFAULT_STATUSES)
