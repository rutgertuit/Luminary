import types

from app.models.research_result import ResearchResult
from app.services.briefing import extract_executive_summary


def test_deep_uses_master_synthesis():
    r = ResearchResult(original_query="q")
    r.master_synthesis = "MASTER"
    r.final_synthesis = "FINAL"
    assert extract_executive_summary(r, depth="DEEP") == "MASTER"


def test_non_deep_uses_final_synthesis():
    r = ResearchResult(original_query="q")
    r.final_synthesis = "FINAL"
    assert extract_executive_summary(r, depth="STANDARD") == "FINAL"


def test_falls_back_to_whatever_is_present():
    r = ResearchResult(original_query="q")
    r.final_synthesis = "ONLY"
    assert extract_executive_summary(r, depth="DEEP") == "ONLY"


def test_empty_returns_empty_string():
    assert extract_executive_summary(ResearchResult(original_query="q"), depth="DEEP") == ""


# --- endpoint smoke ---
import app.routes.ui_api as ui_api
from app.main import create_app


def _client(monkeypatch, result, meta):
    app = create_app()
    app.config["SETTINGS"] = types.SimpleNamespace(gcs_results_bucket="")
    monkeypatch.setattr(ui_api, "_load_research_result", lambda jid, s: (result, meta))
    return app.test_client()


def test_briefing_endpoint_returns_summary(monkeypatch):
    r = ResearchResult(original_query="EV supply chain")
    r.master_synthesis = "MASTER TEXT"
    client = _client(monkeypatch, r, {"depth": "DEEP", "query": "EV supply chain"})
    resp = client.get("/api/research/job1/briefing")
    assert resp.status_code == 200
    assert resp.get_json()["executive_summary"] == "MASTER TEXT"


def test_briefing_endpoint_404(monkeypatch):
    client = _client(monkeypatch, None, None)
    assert client.get("/api/research/missing/briefing").status_code == 404
