"""Research Library Index — a single compact doc listing all completed research.

Gives the voice agents breadth-awareness ("we also researched X") without
loading any topic's full content. Pure functions plus best-effort GCS
persistence (mirrors the checkpoint helpers in ``gcs_client``).
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_INDEX_BLOB = "research_index.json"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def build_entry(job_id: str, title: str, depth: str, created_at: str,
                summary: str, tags: list[str]) -> dict:
    """Build one index entry (summary truncated to 200 chars)."""
    return {
        "job_id": job_id,
        "title": title or "(untitled)",
        "depth": (depth or "").upper(),
        "created_at": created_at,
        "summary": (summary or "").strip()[:200],
        "tags": list(tags or []),
    }


def upsert_entry(entries: list[dict], entry: dict) -> list[dict]:
    """Insert/replace by job_id, return newest-first by created_at."""
    kept = [e for e in entries if e.get("job_id") != entry.get("job_id")]
    kept.append(entry)
    return sorted(kept, key=lambda e: e.get("created_at", ""), reverse=True)


def render_index_markdown(entries: list[dict]) -> str:
    """Render entries to a compact markdown doc for the agent KB."""
    lines = ["# Research Library Index",
             "",
             "Completed research available for reference (newest first):",
             ""]
    for e in entries:
        date = (e.get("created_at") or "")[:10]
        tags = ", ".join(e.get("tags") or [])
        tag_str = f" [{tags}]" if tags else ""
        lines.append(
            f"- **{e.get('title')}** ({e.get('depth')}, {date}, "
            f"id={e.get('job_id')}){tag_str}: {e.get('summary')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GCS persistence (best-effort)
# ---------------------------------------------------------------------------

def load_index(bucket: str) -> list[dict]:
    """Load the index entries list from GCS. Returns [] if absent/error."""
    if not bucket:
        return []
    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(bucket).blob(_INDEX_BLOB)
        if not blob.exists():
            return []
        return json.loads(blob.download_as_text())
    except Exception:
        logger.exception("Failed to load research index")
        return []


def save_index(entries: list[dict], bucket: str) -> None:
    """Persist the index entries list to GCS (best-effort)."""
    if not bucket:
        return
    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(bucket).blob(_INDEX_BLOB)
        blob.upload_from_string(json.dumps(entries), content_type="application/json")
    except Exception:
        logger.exception("Failed to save research index")


def append_completed_job(job_id: str, title: str, depth: str, created_at: str,
                         summary: str, tags: list[str], bucket: str) -> str:
    """Load → upsert → save the index for a completed job; return its markdown."""
    entry = build_entry(job_id, title, depth, created_at, summary, tags)
    entries = upsert_entry(load_index(bucket), entry)
    save_index(entries, bucket)
    return render_index_markdown(entries)
