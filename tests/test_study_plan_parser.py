"""Tests for the V2-shape study plan parser used by deep_pipeline."""

from app.agents.deep_pipeline import parse_v2_study_plan


def test_parses_v2_shape_with_perspectives_and_floor():
    raw = """
    {
      "perspectives": [
        {"id": "reg", "name": "Regulator", "lens": "Rules"},
        {"id": "user", "name": "User", "lens": "Adoption"}
      ],
      "studies": [
        {"title": "S1", "angle": "a", "questions": ["q1"], "covers_perspectives": ["reg"], "source_floor": 10},
        {"title": "S2", "angle": "b", "questions": ["q2"]}
      ]
    }
    """
    perspectives, studies = parse_v2_study_plan(raw)
    assert len(perspectives) == 2
    assert perspectives[0]["id"] == "reg"
    assert len(studies) == 2
    assert studies[0]["source_floor"] == 10
    assert studies[1]["source_floor"] == 8  # default applied


def test_caps_source_floor_at_20():
    raw = '{"perspectives": [], "studies": [{"title": "S", "source_floor": 999}]}'
    _, studies = parse_v2_study_plan(raw)
    assert studies[0]["source_floor"] == 20


def test_floors_source_floor_at_1():
    raw = '{"perspectives": [], "studies": [{"title": "S", "source_floor": 0}]}'
    _, studies = parse_v2_study_plan(raw)
    assert studies[0]["source_floor"] == 1


def test_falls_back_for_legacy_flat_list():
    raw = '[{"title": "S", "angle": "a", "questions": ["q"]}]'
    perspectives, studies = parse_v2_study_plan(raw)
    assert perspectives == [{"id": "general", "name": "General", "lens": "Overall coverage"}]
    assert studies[0]["source_floor"] == 8


def test_empty_perspectives_falls_back_to_default_perspective():
    raw = '{"perspectives": [], "studies": [{"title": "S"}]}'
    perspectives, _ = parse_v2_study_plan(raw)
    assert perspectives == [{"id": "general", "name": "General", "lens": "Overall coverage"}]


def test_garbage_input_returns_default_perspective_and_empty_studies():
    perspectives, studies = parse_v2_study_plan("not json")
    assert perspectives == [{"id": "general", "name": "General", "lens": "Overall coverage"}]
    assert studies == []
