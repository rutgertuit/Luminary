"""Tests for app.agents.json_utils.parse_json_response."""

import logging

import pytest

from app.agents.json_utils import parse_json_response


def test_direct_object():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_direct_array():
    assert parse_json_response('[1, 2, 3]') == [1, 2, 3]


def test_empty_and_none():
    assert parse_json_response("") is None
    assert parse_json_response(None) is None  # type: ignore[arg-type]


def test_strips_markdown_fences():
    text = """```json
    {"hello": "world"}
    ```"""
    assert parse_json_response(text) == {"hello": "world"}


def test_strips_preamble():
    text = 'Sure, here is the data: [{"x": 1}, {"x": 2}]'
    assert parse_json_response(text) == [{"x": 1}, {"x": 2}]


def test_balanced_extraction_with_braces_in_strings():
    """Regression: greedy regex would blow up on braces inside strings."""
    text = 'prefix {"path": "C:/users/{weird}/file.txt", "n": 1} trailing'
    assert parse_json_response(text) == {
        "path": "C:/users/{weird}/file.txt",
        "n": 1,
    }


def test_nested_structures():
    text = 'noise {"outer": {"inner": [1, 2, {"k": "v"}]}} more noise'
    assert parse_json_response(text) == {"outer": {"inner": [1, 2, {"k": "v"}]}}


def test_array_takes_priority_over_object():
    """Study-plan callers expect a list; balanced extractor prefers [ first."""
    text = 'some preamble [1, 2, 3] {"oops": true}'
    assert parse_json_response(text) == [1, 2, 3]


def test_unparseable_logs_and_returns_none(caplog):
    caplog.set_level(logging.WARNING, logger="app.agents.json_utils")
    result = parse_json_response("this is definitely not json at all")
    assert result is None
    assert any("could not parse" in r.message for r in caplog.records)


def test_truncated_json_returns_none(caplog):
    caplog.set_level(logging.WARNING, logger="app.agents.json_utils")
    # Open brace with no close should not hang and should return None.
    assert parse_json_response('{"a": 1, "b": 2') is None
    assert any("could not parse" in r.message for r in caplog.records)
