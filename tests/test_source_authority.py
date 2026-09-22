import pytest

from dandori import cli
from dandori.core import DandoriError


def test_non_matching_source_upsert_preserves_title(ledger):
    a = ledger.upsert({"ref": "vikunja:1", "title": "Hand-written title"}, source="alice", actor="alice")
    b = ledger.upsert(
        {"ref": "vikunja:1", "title": "Vikunja retitle attempt", "status": "inflight"},
        source="vikunja", actor="alice",
    )
    assert b["id"] == a["id"]
    assert b["title"] == "Hand-written title"
    assert b["status"] == "inflight"
    assert b["source"] == "alice"
    assert "vikunja" in b["source_note"]
    assert "alice" in b["source_note"]


def test_non_matching_source_upsert_preserves_description(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "T", "description": "original desc"}, source="alice", actor="alice")
    ledger.upsert({"ref": "vikunja:1", "description": "hostile overwrite"}, source="vikunja", actor="alice")
    result = ledger.show("vikunja:1")
    assert "original desc" in result["body"]
    assert "hostile overwrite" not in result["body"]


def test_non_matching_source_still_applies_other_fields(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="alice", actor="alice")
    b = ledger.upsert(
        {
            "refs": ["vikunja:1", "jira:2"], "links": ["pr:forgejo:tsugite#900"],
            "status": "inflight", "priority": 0, "tags": ["urgent"], "due": "2026-01-01",
        },
        source="vikunja", actor="alice",
    )
    assert "jira:2" in b["refs"]
    assert b["links"] == ["pr:forgejo:tsugite#900"]
    assert b["status"] == "inflight"
    assert b["priority"] == 0
    assert b["tags"] == ["urgent"]
    assert b["due"] == "2026-01-01"


def test_upsert_links_merge_into_existing_links_without_duplicating(ledger):
    a = ledger.upsert({"ref": "vikunja:1", "title": "T", "links": ["commit:abc"]}, source="s", actor="alice")
    assert a["links"] == ["commit:abc"]
    b = ledger.upsert({"ref": "vikunja:1", "links": ["commit:abc", "pr:forgejo:tsugite#900"]}, source="s", actor="alice")
    assert b["links"] == ["commit:abc", "pr:forgejo:tsugite#900"]


def test_upsert_links_respect_prefix_registry(ledger):
    with pytest.raises(DandoriError, match="not registered"):
        ledger.upsert({"ref": "vikunja:1", "title": "T", "links": ["totallymadeup:123"]}, source="s", actor="alice")


def test_matching_source_upsert_overwrites_title(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "T1"}, source="vikunja", actor="alice")
    b = ledger.upsert({"ref": "vikunja:1", "title": "T2"}, source="vikunja", actor="alice")
    assert b["title"] == "T2"
    assert "source_note" not in b


def test_force_overrides_source_authority(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "T1"}, source="alice", actor="alice")
    b = ledger.upsert({"ref": "vikunja:1", "title": "T2"}, source="vikunja", actor="alice", force=True)
    assert b["title"] == "T2"
    assert b["source"] == "vikunja"


def test_create_is_unaffected_by_source_authority(ledger):
    a = ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="vikunja", actor="alice")
    assert a["title"] == "T"
    assert a["source"] == "vikunja"


def test_cli_upsert_prints_source_note(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "Hand title", "--source", "alice", "--actor", "alice"])
    capsys.readouterr()
    rc = cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "Robot retitle",
                   "--source", "vikunja", "--actor", "alice"])
    assert rc == 0
    assert "vikunja" in capsys.readouterr().err
