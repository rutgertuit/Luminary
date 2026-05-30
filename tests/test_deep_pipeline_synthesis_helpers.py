"""Tests for the V2 master-synthesis helpers in deep_pipeline."""

from app.agents.deep_pipeline import (
    _render_reference_list,
    _render_sources_section,
    _strip_sources_section,
)


_REFS = [
    {"n": 1, "url": "https://gov.example/a", "title": "Gov report A",
     "authority": 0.9, "sections": ["exec"]},
    {"n": 2, "url": "https://medium.example/b", "title": "Medium piece B",
     "authority": 0.5, "sections": []},
    {"n": 3, "url": "https://blog.example/c", "title": "",
     "authority": 0.2, "sections": []},
]


def test_render_reference_list_includes_n_url_title_and_tier():
    out = _render_reference_list(_REFS)
    assert "[1]" in out
    assert "https://gov.example/a" in out
    assert "Gov report A" in out
    assert "HIGH AUTHORITY" in out
    assert "MEDIUM AUTHORITY" in out
    assert "LOW AUTHORITY" in out


def test_render_reference_list_handles_missing_title():
    out = _render_reference_list(_REFS)
    # The bare URL stands in when title is empty
    assert "https://blog.example/c" in out


def test_render_sources_section_groups_by_authority():
    out = _render_sources_section(_REFS)
    assert "## Sources" in out
    assert "High authority" in out
    assert "Medium authority" in out
    assert "Lower authority" in out
    # All three should appear
    assert "[1]" in out and "[2]" in out and "[3]" in out


def test_render_sources_section_omits_empty_tiers():
    refs_only_high = [{"n": 1, "url": "https://x", "title": "T", "authority": 0.9, "sections": []}]
    out = _render_sources_section(refs_only_high)
    assert "High authority" in out
    assert "Medium authority" not in out
    assert "Lower authority" not in out


def test_strip_sources_section_removes_sources_heading_and_below():
    text = "Body content [1].\n\n## Sources\n[1] T - https://x"
    out = _strip_sources_section(text)
    assert "Body content" in out
    assert "## Sources" not in out
    assert "https://x" not in out


def test_strip_sources_section_removes_references_heading_too():
    text = "Body content.\n\n# References\n[1] something"
    out = _strip_sources_section(text)
    assert "References" not in out
    assert "[1] something" not in out


def test_strip_sources_section_no_op_when_no_section():
    text = "Just body. No sources block."
    assert _strip_sources_section(text) == "Just body. No sources block."
