import socket
import subprocess
from datetime import datetime, timezone

from dandori import cli
from dandori.core import (
    Ledger,
    host_config_path,
    journal_path,
    machine_host_id,
    save_machine_host_id,
)


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_two_machines_share_a_ledger_and_keep_separate_journal_files(tmp_path, monkeypatch):
    bare = tmp_path / "origin.git"
    _git(["init", "--bare", str(bare)], cwd=tmp_path)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "alpha-config"))
    monkeypatch.setattr(socket, "gethostname", lambda: "alpha")
    seed_dir = tmp_path / "alpha-ledger"
    alpha = Ledger.init(seed_dir)
    assert alpha.host_id == "alpha"
    item = alpha.upsert({"ref": "vikunja:1", "title": "T"}, source="s", actor="alice")
    alpha.log("alpha did some work", ref=item["id"], actor="alice")
    _git(["init"], cwd=seed_dir)
    _git(["remote", "add", "origin", str(bare)], cwd=seed_dir)
    _git(["add", "-A", "."], cwd=seed_dir)
    _git(["commit", "-m", "seed"], cwd=seed_dir)
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=seed_dir,
                             capture_output=True, text=True, check=True).stdout.strip()
    _git(["push", "-u", "origin", branch], cwd=seed_dir)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "beta-config"))
    monkeypatch.setattr(socket, "gethostname", lambda: "beta")
    beta_dir = tmp_path / "beta-ledger"
    _git(["clone", str(bare), str(beta_dir)], cwd=tmp_path)
    beta = Ledger(beta_dir)
    assert beta.host_id == "beta"
    beta.log("beta chimes in", ref=item["id"], actor="bob")

    now = datetime.now(timezone.utc)
    assert journal_path(seed_dir / "journal", "alpha", now).exists()
    assert journal_path(beta_dir / "journal", "beta", now).exists()

    hosts = {e["host"] for e in beta._read_journal()}
    assert hosts == {"alpha", "beta"}


def test_host_set_and_show_round_trip(tmp_path, capsys):
    assert cli.main(["host", "set", "my-machine"]) == 0
    capsys.readouterr()

    assert cli.main(["host"]) == 0
    assert "my-machine" in capsys.readouterr().out


def test_xdg_config_home_respected(tmp_path, monkeypatch):
    custom = tmp_path / "custom-xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
    assert host_config_path() == custom / "dandori" / "host"

    save_machine_host_id("abc")
    assert (custom / "dandori" / "host").read_text().strip() == "abc"


def test_dandori_host_env_overrides_file_and_is_not_persisted(monkeypatch, tmp_path):
    save_machine_host_id("real-host")
    monkeypatch.setenv("DANDORI_HOST", "scratch-test-host")

    assert machine_host_id() == "scratch-test-host"
    assert host_config_path().read_text().strip() == "real-host"
