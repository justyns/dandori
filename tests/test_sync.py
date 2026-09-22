import subprocess

import pytest

from dandori.core import DandoriError, Ledger


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_sync_first_push_to_empty_bare_remote(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    _git(["init"], cwd=data_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=data_dir)

    result = ledger.sync()
    assert result["pushed"] is True

    clone = tmp_path / "clone"
    _git(["clone", str(bare), str(clone)], cwd=tmp_path)
    assert (clone / "items").exists()


def test_sync_second_run_pulls_and_pushes(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    data_dir = tmp_path / "data"
    ledger = Ledger.init(data_dir)
    ledger.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    _git(["init"], cwd=data_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=data_dir)
    ledger.sync()

    ledger.upsert({"ref": "vikunja:2", "title": "B"}, source="s", actor="alice")
    result = ledger.sync()
    assert result["pushed"] is True
    assert result["message"] == "synced with origin"


def test_sync_conflict_aborts_the_rebase_and_reports_the_file(tmp_path):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)
    a_dir = tmp_path / "a"
    a = Ledger.init(a_dir)
    item = a.upsert({"ref": "vikunja:1", "title": "A"}, source="s", actor="alice")
    _git(["init"], cwd=a_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=a_dir)
    a.sync()
    b_dir = tmp_path / "b"
    _git(["clone", str(bare), str(b_dir)], cwd=tmp_path)
    b = Ledger(b_dir)

    a.update(item["id"], priority=1, actor="alice")
    a.sync()
    b.update(item["id"], priority=3, actor="bob")
    with pytest.raises(DandoriError, match=f"conflicts in items/{item['id']}.md"):
        b.sync()

    assert not (b_dir / ".git" / "rebase-merge").exists()
    assert b.show(item["id"])["item"]["priority"] == 3
    with pytest.raises(DandoriError, match="conflicts in"):
        b.sync()
