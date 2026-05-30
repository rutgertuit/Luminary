"""Tests for the LUMINARY_V2_PIPELINE env-flag helper."""

from app.services.model_router import use_v2_pipeline


def test_use_v2_pipeline_off_by_default(monkeypatch):
    monkeypatch.delenv("LUMINARY_V2_PIPELINE", raising=False)
    assert use_v2_pipeline() is False


def test_use_v2_pipeline_on_when_set_to_1(monkeypatch):
    monkeypatch.setenv("LUMINARY_V2_PIPELINE", "1")
    assert use_v2_pipeline() is True


def test_use_v2_pipeline_off_for_other_truthy_values(monkeypatch):
    monkeypatch.setenv("LUMINARY_V2_PIPELINE", "true")
    assert use_v2_pipeline() is False
    monkeypatch.setenv("LUMINARY_V2_PIPELINE", "0")
    assert use_v2_pipeline() is False
    monkeypatch.setenv("LUMINARY_V2_PIPELINE", "yes")
    assert use_v2_pipeline() is False
    monkeypatch.setenv("LUMINARY_V2_PIPELINE", "")
    assert use_v2_pipeline() is False
