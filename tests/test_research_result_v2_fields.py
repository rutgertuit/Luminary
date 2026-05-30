"""Tests for the V2 pipeline fields on ResearchResult and StudyResult."""

from app.models.research_result import ResearchResult, StudyResult


def test_study_result_defaults_for_v2_fields():
    s = StudyResult()
    assert s.source_floor == 8
    assert s.compressed_findings == {}


def test_research_result_defaults_for_v2_fields():
    r = ResearchResult()
    assert r.perspectives == []
    assert r.outline == {}
    assert r.reference_list == []
    assert r.citation_audit == {}


def test_research_result_round_trip_v2_fields():
    r = ResearchResult(
        original_query="Q",
        perspectives=[{"id": "reg", "name": "Regulator", "lens": "rules"}],
        outline={"sections": [{"id": "exec", "title": "Exec"}]},
        reference_list=[{"n": 1, "url": "https://x", "title": "X", "authority": 0.9, "sections": []}],
        citation_audit={"score": 80},
        studies=[StudyResult(title="S", source_floor=10, compressed_findings={"k": "v"})],
    )
    data = r.to_dict()
    r2 = ResearchResult.from_dict(data)
    assert r2.perspectives == r.perspectives
    assert r2.outline == r.outline
    assert r2.reference_list == r.reference_list
    assert r2.citation_audit == r.citation_audit
    assert r2.studies[0].source_floor == 10
    assert r2.studies[0].compressed_findings == {"k": "v"}


def test_research_result_loads_legacy_dict_without_v2_fields():
    legacy = {
        "original_query": "Q",
        "studies": [{"title": "S", "angle": "", "questions": [], "rounds": [], "synthesis": "", "doc_id": ""}],
        "qa_clusters": [],
    }
    r = ResearchResult.from_dict(legacy)
    assert r.perspectives == []
    assert r.studies[0].source_floor == 8


def test_research_result_ignores_unknown_top_level_keys():
    # Future checkpoint with extra metadata must not break from_dict.
    data = {
        "original_query": "Q",
        "studies": [],
        "qa_clusters": [],
        "_checkpoint_phase": "synthesis",
        "_source_registry": {"order": [], "entries": []},
        "future_field": "ignored",
    }
    r = ResearchResult.from_dict(data)
    assert r.original_query == "Q"


def test_research_result_ignores_unknown_study_keys():
    data = {
        "original_query": "Q",
        "studies": [{"title": "S", "future_study_field": "ignored"}],
        "qa_clusters": [],
    }
    r = ResearchResult.from_dict(data)
    assert r.studies[0].title == "S"


def test_research_result_ignores_unknown_qa_cluster_keys():
    data = {
        "original_query": "Q",
        "studies": [],
        "qa_clusters": [{"theme": "T", "future_qa_field": "ignored"}],
    }
    r = ResearchResult.from_dict(data)
    assert r.qa_clusters[0].theme == "T"
