import pytest

from dandori import cli
from dandori.core import ItemNotFoundError


def test_cli_show_renders_tags_due_and_links(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "T",
              "--tags", "ui,tsugite", "--due", "2026-03-04",
              "--links", "commit:abc123", "--source", "s", "--actor", "alice"])
    capsys.readouterr()

    assert cli.main(["show", "vikunja:1", "--dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "due 2026-03-04" in out
    assert "links: commit:abc123" in out
    assert "tags: ui, tsugite" in out


def test_cli_show_omits_tags_line_when_empty(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    cli.main(["upsert", "--dir", data_dir, "--ref", "vikunja:1", "--title", "T", "--source", "s"])
    capsys.readouterr()

    assert cli.main(["show", "vikunja:1", "--dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "tags:" not in out


def test_lookup_never_reads_outside_items_dir(ledger):
    (ledger.data_dir / "evil.md").write_text("---\nid: d-evil\ntitle: x\nstatus: ready\ncreated: '2026-01-01T00:00:00Z'\n---\n")
    with pytest.raises(ItemNotFoundError):
        ledger.show("../evil")
