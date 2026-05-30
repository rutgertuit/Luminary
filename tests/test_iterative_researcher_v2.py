"""Tests for V2 hooks in iterative_researcher.

These tests focus on the helper functions and the public-API contract.
The full ADK runner integration is exercised by the integration smoke test
later in the plan (Task 13).
"""

from app.agents.iterative_researcher import _extract_sources


def test_extract_sources_handles_web_search_format():
    text = "Some claim. [Source: Some Title - https://example.com/a] More text."
    out = _extract_sources(text)
    assert ("https://example.com/a", "Some Title") in out


def test_extract_sources_handles_pull_sources_format():
    text = "[Source: https://example.com/b] [HIGH AUTHORITY]\nSome content"
    out = _extract_sources(text)
    urls = [u for u, _ in out]
    assert "https://example.com/b" in urls


def test_extract_sources_catches_bare_urls():
    text = "Inline reference to https://example.com/c without a tag."
    urls = [u for u, _ in _extract_sources(text)]
    assert "https://example.com/c" in urls


def test_extract_sources_dedupes_within_text():
    text = "[Source: T - https://example.com/d] and again https://example.com/d"
    urls = [u for u, _ in _extract_sources(text)]
    assert urls.count("https://example.com/d") == 1


def test_extract_sources_handles_empty_input():
    assert _extract_sources("") == []
    assert _extract_sources(None) == []  # type: ignore[arg-type]


def test_run_iterative_study_accepts_source_registry_kwarg():
    # Smoke check: the public function signature accepts the new kwarg
    # without us actually executing the body (no GOOGLE_API_KEY needed).
    import inspect
    from app.agents.iterative_researcher import run_iterative_study
    sig = inspect.signature(run_iterative_study)
    assert "source_registry" in sig.parameters
    assert sig.parameters["source_registry"].default is None


def test_extract_sources_preserves_raw_intent():
    # This is a behavior contract: _extract_sources doesn't modify the input.
    text = "Some text with https://example.com/x"
    before = text
    _extract_sources(text)
    assert text == before
