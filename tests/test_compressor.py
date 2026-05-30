"""Tests for app.agents.compressor.compress_findings."""

from unittest.mock import patch

from app.agents.compressor import compress_findings


def test_returns_raw_on_model_failure():
    raw = "Some research finding with https://example.com source."
    with patch("app.agents.compressor._call_gemini_flash", side_effect=RuntimeError("boom")):
        out = compress_findings(raw, target_tokens=200)
    assert out == raw


def test_returns_raw_on_empty_model_response():
    raw = "Finding text."
    with patch("app.agents.compressor._call_gemini_flash", return_value=""):
        out = compress_findings(raw, target_tokens=200)
    assert out == raw


def test_empty_raw_returns_empty_without_model_call():
    with patch("app.agents.compressor._call_gemini_flash") as m:
        out = compress_findings("", target_tokens=200)
    assert out == ""
    m.assert_not_called()


def test_passes_target_tokens_into_prompt(monkeypatch):
    captured = {}

    def fake_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return "compressed"

    monkeypatch.setattr("app.agents.compressor._call_gemini_flash", fake_call)
    compress_findings("raw text", target_tokens=512)
    assert "512" in captured["prompt"]


def test_preserve_urls_flag_appears_in_prompt(monkeypatch):
    captured = {}

    def fake_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return "compressed"

    monkeypatch.setattr("app.agents.compressor._call_gemini_flash", fake_call)
    compress_findings("raw", target_tokens=100, preserve_urls=True)
    assert "URL" in captured["prompt"] or "url" in captured["prompt"]


def test_returns_model_output_on_success(monkeypatch):
    monkeypatch.setattr(
        "app.agents.compressor._call_gemini_flash",
        lambda prompt: "compressed payload",
    )
    out = compress_findings("long raw text with https://x.com [HIGH AUTHORITY]", target_tokens=200)
    assert out == "compressed payload"
