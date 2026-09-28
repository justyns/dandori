from datetime import datetime, timedelta, timezone

import pytest

from dandori import cli
from dandori.core import (
    ActorRequiredError,
    ClaimConflictError,
    parse_item_file,
    render_item_file,
)


def _make_item(ledger, ref="jira:1"):
    return ledger.upsert({"ref": ref, "title": "t"}, source="test", actor="alice")


def test_claim_requires_actor(ledger):
    item = _make_item(ledger)
    with pytest.raises(ActorRequiredError):
        ledger.claim(item["id"], None)


def test_release_requires_actor(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    with pytest.raises(ActorRequiredError):
        ledger.release(item["id"], None)


def test_claim_conflict_by_different_actor(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    with pytest.raises(ClaimConflictError):
        ledger.claim(item["id"], "other")


def test_same_actor_reclaim_is_idempotent(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    result = ledger.claim(item["id"], "alice")
    assert result["claimed_by"] == "alice"


def test_release_by_non_claimant_conflicts(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    with pytest.raises(ClaimConflictError):
        ledger.release(item["id"], "other")


def test_release_clears_claim_fields(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    result = ledger.release(item["id"], "alice")
    assert "claimed_by" not in result
    assert "claimed_at" not in result


def test_claim_does_not_change_status(ledger):
    item = _make_item(ledger)
    assert item["status"] == "ready"
    result = ledger.claim(item["id"], "alice")
    assert result["status"] == "ready"
    journal = ledger._read_journal()
    status_events = [e for e in journal if e["kind"] == "status" and e["ref"] == item["id"]]
    assert status_events == []


def test_release_leaves_status_alone_and_resumes_its_section(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    result = ledger.release(item["id"], "alice")
    assert result["status"] == "ready"
    journal = ledger._read_journal()
    status_events = [e for e in journal if e["kind"] == "status" and e["ref"] == item["id"]]
    assert status_events == []

    sections = ledger.status()["sections"]
    assert "t" in [it["title"] for it in sections["ready"]]
    assert "t" not in [it["title"] for it in sections["in_flight"]]


def test_release_after_done_leaves_done_alone(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    ledger.update(item["id"], status="done")
    result = ledger.release(item["id"], "alice")
    assert result["status"] == "done"


def test_release_noop_does_not_touch_status(ledger):
    item = _make_item(ledger)
    ledger.update(item["id"], status="waiting")
    result = ledger.release(item["id"], "alice")
    assert result["status"] == "waiting"


def test_expired_claim_can_be_taken_by_another_actor(ledger):
    item = _make_item(ledger)
    ledger.claim(item["id"], "alice")
    path = ledger.items_dir / f"{item['id']}.md"
    fm, body = parse_item_file(path)
    fm["claimed_at"] = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(render_item_file(fm, body), encoding="utf-8")

    result = ledger.claim(item["id"], "other")
    assert result["claimed_by"] == "other"


def test_list_claimed_shows_only_claimed_items(ledger, capsys):
    claimed = _make_item(ledger, ref="jira:c1")
    _make_item(ledger, ref="jira:c2")
    ledger.claim(claimed["id"], "alice")

    assert [it["id"] for it in ledger.items(claimed=True)] == [claimed["id"]]
    assert cli.main(["list", "--claimed", "--dir", str(ledger.data_dir)]) == 0
    assert capsys.readouterr().out.count("\n") == 1

