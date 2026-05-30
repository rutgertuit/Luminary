import types

import app.services.research_orchestrator as orch


class _StudyResult:
    def __init__(self, title, synthesis):
        self.title, self.synthesis = title, synthesis
        self.doc_id = ""


def _settings():
    return types.SimpleNamespace(
        elevenlabs_api_key="k", gcs_results_bucket="", max_agent_kb_docs=3,
        elevenlabs_agent_id_maya="m", elevenlabs_agent_id_barnaby="",
        elevenlabs_agent_id_consultant="", elevenlabs_agent_id_rutger="",
    )


def test_deep_upload_uploads_single_consolidated_doc(monkeypatch):
    calls = {"uploads": 0, "order": []}
    monkeypatch.setattr(
        orch, "_upload_with_retry",
        lambda text, name, api_key: calls.__setitem__("uploads", calls["uploads"] + 1) or "doc1",
    )
    monkeypatch.setattr(orch.elevenlabs_client, "enforce_kb_limit",
                        lambda *a, **k: calls["order"].append("evict"))
    monkeypatch.setattr(orch, "_attach_with_rag_retry",
                        lambda fn, label: calls["order"].append("attach"))
    monkeypatch.setattr(orch.gcs_client, "publish_results", lambda *a, **k: "")

    result = types.SimpleNamespace(
        studies=[_StudyResult("S1", "syn1"), _StudyResult("S2", "syn2")],
        master_synthesis="MASTER", qa_clusters=[], qa_summary="",
        synthesis_score=0, synthesis_scores={}, refinement_rounds=0,
        strategic_analysis="", all_doc_ids=[],
    )
    orch._handle_deep_upload(result, "the query", "conv1234", "m", _settings())

    assert calls["uploads"] == 1                      # ONE consolidated doc, not 6-10
    assert calls["order"] == ["attach", "evict"]      # evict AFTER attach
