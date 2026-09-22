import subprocess

from dandori import cli
from dandori.core import Ledger


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_log_sync_flag_pushes_to_origin(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    _git(["init"], cwd=data_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=data_dir)
    ledger.sync()

    rc = cli.main(["log", "note", "--dir", str(data_dir), "--actor", "alice", "--sync"])
    assert rc == 0

    clone = tmp_path / "clone"
    _git(["clone", str(bare), str(clone)], cwd=tmp_path)
    journal_files = list((clone / "journal").glob("*.jsonl"))
    assert any("note" in f.read_text() for f in journal_files)


def test_claim_no_sync_flag_performs_no_git_operations(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    ledger.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")

    calls = []
    real_run = subprocess.run

    def spy_run(args, *a, **kw):
        if args[0] == "git":
            calls.append(args)
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy_run)
    rc = cli.main(["claim", next((data_dir / "items").glob("*.md")).stem,
                   "--dir", str(data_dir), "--actor", "alice", "--no-sync"])
    assert rc == 0
    assert calls == []

