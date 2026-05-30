"""Active-prep pointer logic — which research a car call is scoped to.

``resolve_active_prep`` is pure (no I/O); the stored value lives in GCS via
``gcs_client.save_active_prep`` / ``load_active_prep``.
"""
from __future__ import annotations


def resolve_active_prep(stored_job_id: str, archive_metas: list[dict]) -> str:
    """Return the job_id to scope a call to.

    Use the stored id if it still exists in the archive; otherwise default to
    the newest *completed* job. Returns "" if nothing is available.
    """
    ids = {m.get("job_id") for m in archive_metas}
    if stored_job_id and stored_job_id in ids:
        return stored_job_id
    completed = [m for m in archive_metas if (m.get("status") or "").lower() == "completed"]
    if not completed:
        return ""
    newest = max(completed, key=lambda m: m.get("created_at", ""))
    return newest.get("job_id", "")
