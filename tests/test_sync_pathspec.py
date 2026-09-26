import subprocess

import dandori.core as core
from dandori.core import Ledger


def _git(args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def test_eager_stage_and_commit_never_uses_add_dash_a(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    _git(["init"], cwd=data_dir)

    calls = []
    real_run = subprocess.run

    def spy(args, *a, **kw):
        if args[0] == "git":
            calls.append(args)
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    core._eager_stage_and_commit(data_dir, "msg")

    add_calls = [c for c in calls if len(c) > 1 and c[1] == "add"]
    commit_calls = [c for c in calls if len(c) > 1 and c[1] == "commit"]
    assert len(add_calls) == 1 and "-A" not in add_calls[0]
    assert list(add_calls[0][2:]) == ["--", "config.yaml", "items", "journal"]
    assert len(commit_calls) == 1
    commit_pathspec = commit_calls[0][commit_calls[0].index("--") + 1:]
    assert "-A" not in commit_calls[0]
    assert all(p.startswith(("config.yaml", "items/", "journal/")) for p in commit_pathspec)


def test_sync_does_not_commit_when_only_a_humans_file_is_staged(tmp_path):
    """The commit pathspec matters independently of the add pathspec: a file
    a human staged elsewhere in a shared repo must not ride along."""
    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    _git(["init"], cwd=data_dir)
    ledger.sync()

    (data_dir / "src.py").write_text("print(1)\n")
    _git(["add", "src.py"], cwd=data_dir)

    result = ledger.sync()
    assert result["committed"] is False

    status = _git(["status", "--porcelain"], cwd=data_dir).stdout.splitlines()
    assert "A  src.py" in status


def test_sync_excludes_a_humans_staged_file_from_the_commit_it_does_make(tmp_path):
    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    _git(["init"], cwd=data_dir)

    (data_dir / "src.py").write_text("print(1)\n")
    _git(["add", "src.py"], cwd=data_dir)

    result = ledger.sync()
    assert result["committed"] is True

    show = _git(["show", "--name-only", "--pretty=format:", "HEAD"], cwd=data_dir)
    committed_files = show.stdout.split()
    assert "src.py" not in committed_files
    assert any(f.startswith("items/") for f in committed_files)

    status = _git(["status", "--porcelain"], cwd=data_dir).stdout.splitlines()
    assert "A  src.py" in status


def test_eager_claim_excludes_a_humans_staged_file_from_the_commit(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    item = ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    _git(["init"], cwd=data_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=data_dir)
    ledger.sync()

    (data_dir / "src.py").write_text("print(1)\n")
    _git(["add", "src.py"], cwd=data_dir)

    result = ledger.claim(item["id"], "alice")
    assert result["claimed_by"] == "alice"

    log = _git(["log", "--name-only", "--pretty=format:--%H--"], cwd=data_dir).stdout
    assert "src.py" not in log
    status = _git(["status", "--porcelain"], cwd=data_dir).stdout.splitlines()
    assert "A  src.py" in status


def test_eager_claim_names_conflicting_paths(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    a_dir = tmp_path / "a"
    a = Ledger.init(a_dir)
    item = a.upsert({"ref": "vikunja:1", "title": "original"}, source="s", actor="alice")
    _git(["init"], cwd=a_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=a_dir)
    a.sync()

    b_dir = tmp_path / "b"
    _git(["clone", str(bare), str(b_dir)], cwd=tmp_path)
    b = Ledger(b_dir)
    b.upsert({"ref": "vikunja:1", "title": "changed by bob"}, source="s", actor="bob")
    b.sync()

    a.upsert({"ref": "vikunja:1", "title": "changed by alice"}, source="s", actor="alice")

    result = a.claim(item["id"], "alice")
    assert result["claimed_by"] == "alice"
    assert "sync_warning" in result
    assert f"items/{item['id']}.md" in result["sync_warning"]
    assert "conflict" in result["sync_warning"]
