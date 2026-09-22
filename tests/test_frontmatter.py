from dandori.core import (
    FIELD_ORDER,
    canonical_frontmatter,
    parse_item_file,
    render_item_file,
)


def test_canonical_frontmatter_round_trip(tmp_path):
    fm = {
        "status": "ready",
        "id": "d-1234",
        "title": "T",
        "refs": ["a:1"],
        "type": "task",
        "priority": 2,
        "tags": [],
        "deps": [],
        "source": "s",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }
    body = "## Description\n\n## Acceptance criteria\n\n## Notes\n"
    text = render_item_file(fm, body)

    path = tmp_path / "d-1234.md"
    path.write_text(text)
    parsed_fm, parsed_body = parse_item_file(path)

    assert parsed_fm["id"] == "d-1234"
    assert parsed_fm["refs"] == ["a:1"]
    assert parsed_body == body

    assert render_item_file(parsed_fm, parsed_body) == text

    ordered_keys = list(canonical_frontmatter(parsed_fm).keys())
    assert ordered_keys == [k for k in FIELD_ORDER if k in fm]


def test_canonical_frontmatter_includes_claim_fields_only_when_present():
    fm = canonical_frontmatter({"id": "d-1", "title": "t", "status": "ready"})
    assert "claimed_by" not in fm

    fm = canonical_frontmatter({"id": "d-1", "title": "t", "status": "inflight",
                                 "claimed_by": "alice", "claimed_at": "2026-01-01T00:00:00Z"})
    keys = list(fm.keys())
    assert keys.index("claimed_by") > keys.index("status")
