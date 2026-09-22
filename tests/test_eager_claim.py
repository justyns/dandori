import subprocess

import pytest

import dandori.core as core
from dandori.core import ClaimConflictError, Ledger, load_config, save_config


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _clone(tmp_path, bare, name, host):
    dest = tmp_path / name
    _git(["clone", str(bare), str(dest)], cwd=tmp_path)
    ledger = Ledger(dest)
    ledger.host_id = host
    return ledger


def _make_shared_repo(tmp_path):
    """A bare origin plus clone A, already carrying one item and pushed."""
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    seed = tmp_path / "seed"
    ledger = Ledger.init(seed)
    item = ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    _git(["init"], cwd=seed)
    _git(["remote", "add", "origin", str(bare)], cwd=seed)
    _git(["add", "-A", "."], cwd=seed)
    _git(["commit", "-m", "seed"], cwd=seed)
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=seed,
                             capture_output=True, text=True, check=True).stdout.strip()
    _git(["push", "-u", "origin", branch], cwd=seed)
    return bare, item["id"]


def test_a_claims_b_pulls_and_sees_it_then_conflicts(tmp_path):
    bare, item_id = _make_shared_repo(tmp_path)
    a = _clone(tmp_path, bare, "a", "hosta")
    b = _clone(tmp_path, bare, "b", "hostb")

    a.claim(item_id, "alice")

    with pytest.raises(ClaimConflictError, match="already claimed by alice"):
        b.claim(item_id, "other")

    fm = b._resolve(item_id)[1]
    assert fm["claimed_by"] == "alice"


def test_push_race_a_loses_cleanly_and_keeps_pending_work(tmp_path, monkeypatch):
    bare, item_id = _make_shared_repo(tmp_path)
    a = _clone(tmp_path, bare, "a", "hosta")
    b = _clone(tmp_path, bare, "b", "hostb")
    pending = a.upsert({"ref": "vikunja:99", "title": "pending"}, source="s", actor="alice")

    # A pulls and writes its claim locally, then right before A's push, B
    # claims the same item on its own clone and pushes first.
    real_eager_push = core._eager_push
    triggered = {"done": False}

    def patched_push(data_dir):
        if not triggered["done"] and data_dir == a.data_dir:
            triggered["done"] = True
            b.claim(item_id, "b-actor")
        return real_eager_push(data_dir)

    monkeypatch.setattr(core, "_eager_push", patched_push)
    with pytest.raises(ClaimConflictError, match="claim lost to b-actor"):
        a.claim(item_id, "a-actor")

    status = subprocess.run(["git", "status", "--porcelain"], cwd=a.data_dir,
                             capture_output=True, text=True, check=True)
    assert status.stdout.strip() == ""
    assert a._resolve(item_id)[1]["claimed_by"] == "b-actor"
    assert a._resolve(pending["id"])[1]["title"] == "pending"
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=a.data_dir,
                             capture_output=True, text=True, check=True).stdout.strip()
    on_origin = subprocess.run(["git", "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"], cwd=a.data_dir)
    assert on_origin.returncode == 0


def test_offline_claim_degrades_with_warning(tmp_path):
    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    item = ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    _git(["init"], cwd=data_dir)
    _git(["remote", "add", "origin", str(tmp_path / "does-not-exist.git")], cwd=data_dir)

    result = ledger.claim(item["id"], "alice")
    assert result["claimed_by"] == "alice"
    assert "local-only" in result["sync_warning"]


def test_eager_claims_false_skips_git_entirely(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    item = ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    save_config(data_dir, {**load_config(data_dir), "sync": {"eager_claims": False}})

    calls = []
    real_run = subprocess.run

    def spy_run(args, *a, **kw):
        if args[0] == "git":
            calls.append(args)
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy_run)
    result = ledger.claim(item["id"], "alice")
    assert result["claimed_by"] == "alice"
    assert calls == []


def test_eager_claim_commits_pending_upsert_before_pull(tmp_path):
    bare, item_id = _make_shared_repo(tmp_path)
    a = _clone(tmp_path, bare, "a", "hosta")

    # Lazy upsert leaves the clone's working tree dirty (upsert never
    # touches git). Claim must commit that before it pulls, or the pull
    # refuses with "you have uncommitted changes".
    a.upsert({"ref": "vikunja:1", "title": "T changed"}, source="s", actor="alice")
    result = a.claim(item_id, "alice")

    assert "sync_warning" not in result
    status = subprocess.run(["git", "status", "--porcelain"], cwd=a.data_dir,
                             capture_output=True, text=True, check=True)
    assert status.stdout.strip() == ""

    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=a.data_dir,
                             capture_output=True, text=True, check=True).stdout.strip()
    local_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=a.data_dir,
                                 capture_output=True, text=True, check=True).stdout.strip()
    origin_head = subprocess.run(["git", "rev-parse", f"origin/{branch}"], cwd=a.data_dir,
                                  capture_output=True, text=True, check=True).stdout.strip()
    assert local_head == origin_head


def test_release_follows_pull_write_push_pattern(tmp_path):
    bare, item_id = _make_shared_repo(tmp_path)
    a = _clone(tmp_path, bare, "a", "hosta")
    b = _clone(tmp_path, bare, "b", "hostb")

    a.claim(item_id, "alice")
    a.release(item_id, "alice")

    b.claim(item_id, "b-actor")
    fm = b._resolve(item_id)[1]
    assert fm["claimed_by"] == "b-actor"
