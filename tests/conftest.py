import pytest

from dandori.core import Ledger, save_machine_host_id


@pytest.fixture(autouse=True)
def isolated_host_config(tmp_path, monkeypatch):
    """Keeps every test off the real machine's $XDG_CONFIG_HOME/dandori/host."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("DANDORI_HOST", raising=False)
    save_machine_host_id("testhost")


@pytest.fixture
def ledger(tmp_path):
    return Ledger.init(tmp_path / "data")
