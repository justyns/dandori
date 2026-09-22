import subprocess

import dandori.core as core
from dandori.core import Ledger


def _git(args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _branch(cwd):
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


def _leave_a_stuck_empty_commit_rebase(a_dir, branch):
    """Fabricates the exact 2026-09-14 failure: a rebase that stopped with a
    clean tree because the replayed commit became empty, leaving
    .git/rebase-merge behind. --reapply-cherry-picks forces git past its own
    redundant-commit shortcut so the stop actually happens."""
    _git(["fetch", "origin", branch], cwd=a_dir)
    _git(["rebase", "--reapply-cherry-picks", "--empty=stop", f"origin/{branch}"],
         cwd=a_dir, check=False)
    assert (a_dir / ".git" / "rebase-merge").exists(), "fixture did not reach the stuck state"


def test_sync_recovers_from_a_stale_rebase_left_by_an_empty_commit(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    a_dir = tmp_path / "a"
    a = Ledger.init(a_dir)
    a.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    _git(["init"], cwd=a_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=a_dir)
    a.sync()

    b_dir = tmp_path / "b"
    _git(["clone", str(bare), str(b_dir)], cwd=tmp_path)

    config = b_dir / "config.yaml"
    config.write_text(config.read_text() + "note: shared\n")
    _git(["add", "config.yaml"], cwd=b_dir)
    _git(["commit", "-m", "b note"], cwd=b_dir)
    branch = _branch(b_dir)
    _git(["push", "origin", branch], cwd=b_dir)

    # A makes the same content change under its own commit (a different
    # message keeps the commit hash distinct from B's, so git must actually
    # replay it during rebase instead of recognizing it as the same commit).
    config = a_dir / "config.yaml"
    config.write_text(config.read_text() + "note: shared\n")
    _git(["add", "config.yaml"], cwd=a_dir)
    _git(["commit", "-m", "a note"], cwd=a_dir)

    _leave_a_stuck_empty_commit_rebase(a_dir, branch)

    result = a.sync()

    assert not (a_dir / ".git" / "rebase-merge").exists()
    assert result["pushed"] is True
    ledger_status = _git(["status", "--porcelain", "--", *core.LEDGER_PATHS], cwd=a_dir).stdout.strip()
    assert ledger_status == ""
    local_head = _git(["rev-parse", "HEAD"], cwd=a_dir).stdout.strip()
    origin_head = _git(["rev-parse", f"origin/{branch}"], cwd=a_dir).stdout.strip()
    assert local_head == origin_head


def test_claim_recovers_from_a_stale_rebase_left_by_an_empty_commit(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    a_dir = tmp_path / "a"
    a = Ledger.init(a_dir)
    item = a.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    _git(["init"], cwd=a_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=a_dir)
    a.sync()

    b_dir = tmp_path / "b"
    _git(["clone", str(bare), str(b_dir)], cwd=tmp_path)
    config = b_dir / "config.yaml"
    config.write_text(config.read_text() + "note: shared\n")
    _git(["add", "config.yaml"], cwd=b_dir)
    _git(["commit", "-m", "b note"], cwd=b_dir)
    branch = _branch(b_dir)
    _git(["push", "origin", branch], cwd=b_dir)

    config = a_dir / "config.yaml"
    config.write_text(config.read_text() + "note: shared\n")
    _git(["add", "config.yaml"], cwd=a_dir)
    _git(["commit", "-m", "a note"], cwd=a_dir)

    _leave_a_stuck_empty_commit_rebase(a_dir, branch)

    result = a.claim(item["id"], "alice")

    assert not (a_dir / ".git" / "rebase-merge").exists()
    assert result["claimed_by"] == "alice"
    assert "sync_warning" not in result


def test_pull_rebase_drops_empty_commits_instead_of_stopping(tmp_path, monkeypatch):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    a_dir = tmp_path / "a"
    a = Ledger.init(a_dir)
    a.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    _git(["init"], cwd=a_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=a_dir)
    a.sync()

    calls = []
    real_run = subprocess.run

    def spy(args, *a_, **kw):
        if args[0] == "git":
            calls.append(args)
        return real_run(args, *a_, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    core._pull_rebase(a_dir)

    rebase_calls = [c for c in calls if len(c) > 1 and c[1] == "rebase"]
    assert len(rebase_calls) == 1
    assert "--empty=drop" in rebase_calls[0]
