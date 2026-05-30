"""Tests for app.agents.outline_generator.parse_outline."""

from app.agents.outline_generator import parse_outline, DEFAULT_OUTLINE


def test_parses_valid_outline():
    raw = """
    ```json
    {
      "title": "Briefing: X",
      "sections": [
        {"id": "exec", "title": "Executive Summary", "target_perspectives": ["reg"],
         "relevant_study_indices": [0, 1], "key_questions": ["q"]}
      ]
    }
    ```
    """
    out = parse_outline(raw)
    assert out["title"].startswith("Briefing")
    assert out["sections"][0]["id"] == "exec"


def test_falls_back_on_garbage():
    out = parse_outline("not json")
    assert out == DEFAULT_OUTLINE


def test_falls_back_on_missing_sections():
    out = parse_outline('{"title": "T"}')
    assert out == DEFAULT_OUTLINE


def test_falls_back_on_empty_sections_list():
    out = parse_outline('{"title": "T", "sections": []}')
    assert out == DEFAULT_OUTLINE


def test_accepts_dict_input_directly():
    raw = {"title": "T", "sections": [{"id": "exec", "title": "Exec"}]}
    out = parse_outline(raw)  # type: ignore[arg-type]
    assert out["sections"][0]["id"] == "exec"


def test_default_outline_has_required_first_and_last_sections():
    assert DEFAULT_OUTLINE["sections"][0]["id"] == "exec_summary"
    assert DEFAULT_OUTLINE["sections"][-1]["id"] == "confidence"
