"""Tests for app.agents.citation_verifier helpers."""

from app.agents.citation_verifier import extract_citation_numbers, parse_audit


def test_extract_citation_numbers_basic():
    text = "Foo [1] bar [2][3]. Baz [10]."
    assert extract_citation_numbers(text) == [1, 2, 3, 10]


def test_extract_citation_numbers_dedupes_in_order():
    text = "[1] [2] [1] [3]"
    assert extract_citation_numbers(text) == [1, 2, 3]


def test_extract_citation_numbers_empty_input():
    assert extract_citation_numbers("") == []
    assert extract_citation_numbers(None) == []  # type: ignore[arg-type]


def test_extract_citation_numbers_ignores_non_citation_brackets():
    # [foo] and [bar baz] should not be treated as citation markers.
    text = "Note [foo] and [bar baz], but [4] is a real cite."
    assert extract_citation_numbers(text) == [4]


def test_parse_audit_valid():
    raw = """
    {
      "unsupported_claims": [
        {"claim": "X happened", "citation_num": 2, "severity": "high", "reason": "..."}
      ],
      "weak_citations": [{"citation_num": 3, "reason": "low authority"}],
      "score": 78
    }
    """
    out = parse_audit(raw)
    assert out["score"] == 78
    assert out["unsupported_claims"][0]["severity"] == "high"
    assert out["weak_citations"][0]["citation_num"] == 3


def test_parse_audit_falls_back_on_garbage():
    out = parse_audit("not json")
    assert out == {"unsupported_claims": [], "weak_citations": [], "score": 0}


def test_parse_audit_fills_missing_keys():
    # Valid JSON dict but missing some required keys → fill in defaults.
    out = parse_audit('{"score": 42}')
    assert out["score"] == 42
    assert out["unsupported_claims"] == []
    assert out["weak_citations"] == []
