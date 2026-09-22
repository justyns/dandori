import subprocess

from dandori.core import derive_project_from_cwd


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_explicit_project_wins(ledger):
    item = ledger.upsert({"ref": "vikunja:1", "title": "A", "project": "widgets"}, source="s", actor="alice")
    assert item["project"] == "widgets"


def test_no_project_suppresses_derivation(ledger, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["remote", "add", "origin", "git@example.com:owner/repo.git"], cwd=repo)
    monkeypatch.chdir(repo)

    item = ledger.upsert({"ref": "vikunja:2", "title": "A", "no_project": True}, source="s", actor="alice")
    assert "project" not in item


def test_update_does_not_rewrite_derived_project(ledger, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["remote", "add", "origin", "git@example.com:owner/repo.git"], cwd=repo)
    monkeypatch.chdir(repo)

    a = ledger.upsert({"ref": "vikunja:3", "title": "A"}, source="s", actor="alice")
    assert a["project"] == "repo"

    monkeypatch.chdir(tmp_path)
    b = ledger.upsert({"ref": "vikunja:3", "title": "A changed"}, source="s", actor="alice")
    assert b["project"] == "repo"


def test_update_sets_and_clears_project(ledger):
    item = ledger.upsert({"ref": "vikunja:6", "title": "A", "project": "widgets"}, source="s", actor="alice")
    assert ledger.update(item["id"], project="gadgets")["project"] == "gadgets"
    assert "project" not in ledger.update(item["id"], project="")


def test_derive_project_from_cwd_ssh_url(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["remote", "add", "origin", "git@example.com:owner/my-repo.git"], cwd=repo)
    assert derive_project_from_cwd(repo) == "my-repo"


def test_derive_project_from_cwd_https_url(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["remote", "add", "origin", "https://example.com/owner/my-repo.git"], cwd=repo)
    assert derive_project_from_cwd(repo) == "my-repo"


def test_derive_project_from_cwd_falls_back_to_first_remote_alphabetically(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["remote", "add", "zremote", "git@example.com:owner/z-repo.git"], cwd=repo)
    _git(["remote", "add", "aremote", "git@example.com:owner/a-repo.git"], cwd=repo)
    assert derive_project_from_cwd(repo) == "a-repo"


def test_derive_project_from_cwd_falls_back_to_toplevel_basename(tmp_path):
    repo = tmp_path / "my-toplevel"
    repo.mkdir()
    _git(["init"], cwd=repo)
    assert derive_project_from_cwd(repo) == "my-toplevel"


def test_derive_project_from_cwd_outside_git_repo_is_none(tmp_path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    assert derive_project_from_cwd(outside) is None


def test_list_and_status_filter_by_project(ledger):
    ledger.upsert({"ref": "vikunja:4", "title": "A", "project": "widgets"}, source="s", actor="alice")
    ledger.upsert({"ref": "vikunja:5", "title": "B", "project": "gadgets"}, source="s", actor="alice")

    widgets = ledger.items(project="widgets")
    assert [i["title"] for i in widgets] == ["A"]

    status = ledger.status(project="widgets")
    assert [i["title"] for i in status["ready"]] == ["A"]
