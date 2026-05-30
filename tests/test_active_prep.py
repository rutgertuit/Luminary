from app.services.active_prep import resolve_active_prep


def test_resolve_uses_stored_when_valid():
    archive = [{"job_id": "a", "status": "completed", "created_at": "2026-05-01"},
               {"job_id": "b", "status": "completed", "created_at": "2026-05-02"}]
    assert resolve_active_prep("a", archive) == "a"


def test_resolve_falls_back_to_newest_completed_when_stored_missing():
    archive = [{"job_id": "a", "status": "completed", "created_at": "2026-05-01"},
               {"job_id": "b", "status": "completed", "created_at": "2026-05-02"}]
    assert resolve_active_prep("", archive) == "b"        # newest
    assert resolve_active_prep("zzz", archive) == "b"     # stale stored id


def test_resolve_ignores_non_completed_for_default():
    archive = [{"job_id": "a", "status": "completed", "created_at": "2026-05-01"},
               {"job_id": "b", "status": "running", "created_at": "2026-05-09"}]
    assert resolve_active_prep("", archive) == "a"


def test_resolve_empty_archive_returns_empty():
    assert resolve_active_prep("", []) == ""
