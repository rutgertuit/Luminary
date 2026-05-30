import types

import app.routes.ui_api as ui_api
from app.main import create_app


def _client(monkeypatch, stored="", archive=None):
    app = create_app()
    app.config["SETTINGS"] = types.SimpleNamespace(gcs_results_bucket="b")
    state = {"stored": stored}
    monkeypatch.setattr(ui_api.gcs_client, "load_active_prep", lambda b: state["stored"])
    monkeypatch.setattr(ui_api.gcs_client, "save_active_prep",
                        lambda jid, b: state.update(stored=jid))
    monkeypatch.setattr(ui_api.gcs_client, "list_results_metadata",
                        lambda b, **k: archive or [])
    return app.test_client(), state


def test_get_active_prep_defaults_to_newest(monkeypatch):
    archive = [{"job_id": "a", "status": "completed", "created_at": "2026-05-01"},
               {"job_id": "b", "status": "completed", "created_at": "2026-05-02"}]
    client, _ = _client(monkeypatch, stored="", archive=archive)
    resp = client.get("/api/active-prep")
    assert resp.status_code == 200
    assert resp.get_json()["job_id"] == "b"


def test_put_active_prep_persists(monkeypatch):
    client, state = _client(monkeypatch, stored="",
                            archive=[{"job_id": "x", "status": "completed", "created_at": "1"}])
    resp = client.put("/api/active-prep", json={"job_id": "x"})
    assert resp.status_code == 200
    assert state["stored"] == "x"


def test_put_active_prep_requires_job_id(monkeypatch):
    client, _ = _client(monkeypatch)
    assert client.put("/api/active-prep", json={}).status_code == 400
