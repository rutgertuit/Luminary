"""Tests for app.services.source_registry.SourceRegistry."""

from app.services.source_registry import SourceRegistry


def test_add_returns_ref_num_starting_at_1():
    reg = SourceRegistry()
    assert reg.add("https://example.com/a", "A", "snippet A", 0.9) == 1
    assert reg.add("https://example.com/b", "B", "snippet B", 0.5) == 2


def test_add_is_idempotent_on_canonical_url():
    reg = SourceRegistry()
    n1 = reg.add("https://Example.com/a?b=1&a=2#frag", "T", "s", 0.9)
    n2 = reg.add("https://example.com/a?a=2&b=1", "T", "s", 0.9)
    assert n1 == n2 == 1
    assert len(reg.get_reference_list()) == 1


def test_add_fills_missing_fields_on_revisit():
    reg = SourceRegistry()
    reg.add("https://example.com/a", "", "", 0.0)
    reg.add("https://example.com/a", "Real title", "snippet", 0.8)
    refs = reg.get_reference_list()
    assert refs[0]["title"] == "Real title"
    assert refs[0]["authority"] == 0.8


def test_record_usage_tracks_sections_per_ref():
    reg = SourceRegistry()
    reg.add("https://example.com/a", "A", "s", 0.9)
    reg.record_usage(1, "exec_summary")
    reg.record_usage(1, "key_findings")
    assert reg.get_reference_list()[0]["sections"] == ["exec_summary", "key_findings"]


def test_count_for_study_attributes_sources_per_study():
    reg = SourceRegistry()
    reg.add("https://example.com/a", "A", "s", 0.9, study_index=0)
    reg.add("https://example.com/b", "B", "s", 0.9, study_index=0)
    reg.add("https://example.com/c", "C", "s", 0.9, study_index=1)
    assert reg.count_for_study(0) == 2
    assert reg.count_for_study(1) == 1


def test_round_trip_to_from_dict():
    reg = SourceRegistry()
    reg.add("https://example.com/a", "A", "s", 0.9, study_index=0)
    reg.record_usage(1, "exec_summary")
    data = reg.to_dict()
    restored = SourceRegistry.from_dict(data)
    refs = restored.get_reference_list()
    assert refs[0]["url"] == "https://example.com/a"
    assert refs[0]["sections"] == ["exec_summary"]
    assert restored.count_for_study(0) == 1


def test_registry_increments_counters(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.services.source_registry.increment",
        lambda name, n=1: calls.append(name),
    )
    reg = SourceRegistry()
    reg.add("https://example.com/a", "A", "s", 0.9)
    reg.add("https://example.com/a", "A", "s", 0.9)  # dedup hit
    assert "registry_urls_added" in calls
    assert "registry_dedup_hits" in calls
