import pytest

from dandori import cli


def test_cli_guide_fails_cleanly_outside_a_ledger(tmp_path, capsys):
    rc = cli.main(["guide", "--dir", str(tmp_path / "nope")])
    assert rc != 0
    assert "ledger" in capsys.readouterr().err.lower()


def test_guide_uses_real_project_actor_and_tags_from_the_ledger(ledger):
    ledger.upsert({"ref": "vikunja:1", "title": "T", "project": "widgets", "tags": ["ui"]},
                  source="s", actor="bob")
    data = ledger.guide()
    assert data["example_actor"] == "bob"
    assert data["example_project"] == "widgets"
    assert data["tags"] == ["ui"]
    assert data["projects"] == ["widgets"]


def test_cli_guide_output_mentions_host_id_prefixes_and_stays_under_60_lines(tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    cli.main(["init", "--dir", data_dir])
    capsys.readouterr()

    assert cli.main(["guide", "--dir", data_dir]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()

    assert len(lines) <= 60
    assert "testhost" in out
    assert "forgejo" in out


def test_cli_help_epilog_points_to_guide(capsys):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--help"])
    out = capsys.readouterr().out
    assert "dori guide" in out
