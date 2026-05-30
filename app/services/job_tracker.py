"""In-memory thread-safe job state tracker for UI-triggered research."""

import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class JobStatus(Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobInfo:
    job_id: str
    query: str
    depth: str
    status: JobStatus = JobStatus.PENDING
    phase: str = ""
    result_url: str = ""
    error: str = ""
    elevenlabs_doc_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str = ""
    parent_job_id: str = ""  # for amendments — links to original research
    # Structured progress for DEEP pipeline
    study_plan: list = field(default_factory=list)
    study_progress: list = field(default_factory=list)  # [{title, status, rounds}]
    current_step: str = ""  # e.g. "study_2", "synthesis", "refinement"
    # Phase timing: {phase_name: {"start": epoch, "end": epoch}}
    phase_timings: dict = field(default_factory=dict)
    # Research stats: {web_searches, pages_read, ...}
    research_stats: dict = field(default_factory=dict)
    # NotebookLM individual source URLs
    notebooklm_urls: list = field(default_factory=list)
    # Podcast generation
    podcast_job_id: str = ""
    podcast_status: str = ""  # analyzing/scripting/generating/completed/failed
    podcast_style: str = ""
    podcast_audio_url: str = ""
    podcast_script_preview: str = ""
    # Research plan (populated during planning phase, before execution)
    plan_data: dict = field(default_factory=dict)
    # Time budget in seconds (0 = no limit)
    time_budget: int = 0
    _last_phase_key: str = ""
    _cancel_requested: bool = False


_jobs: dict[str, JobInfo] = {}
_lock = threading.Lock()


def create_job(query: str, depth: str) -> str:
    """Create a new job and return its ID (12-char hex)."""
    job_id = secrets.token_hex(6)
    job = JobInfo(job_id=job_id, query=query, depth=depth)
    with _lock:
        _jobs[job_id] = job
    return job_id


def get_job(job_id: str) -> Optional[JobInfo]:
    """Return job info or None if not found."""
    with _lock:
        return _jobs.get(job_id)


def update_job(job_id: str, **kwargs) -> None:
    """Update fields on an existing job."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)


def record_phase_timing(job_id: str, phase_key: str) -> None:
    """Record that a new pipeline phase has started.

    Automatically ends the previous phase and starts timing the new one.
    Phase keys should be normalized (e.g. 'planning', 'studies', 'synthesis').
    """
    now = time.time()
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        # End previous phase
        if job._last_phase_key and job._last_phase_key in job.phase_timings:
            prev = job.phase_timings[job._last_phase_key]
            if "end" not in prev:
                prev["end"] = now
                prev["duration"] = now - prev["start"]
        # Start new phase (don't overwrite if same phase restarts, e.g. study_0 then study_1)
        if phase_key not in job.phase_timings:
            job.phase_timings[phase_key] = {"start": now}
        job._last_phase_key = phase_key


def finalize_timings(job_id: str) -> dict:
    """End all open timings and return the complete phase_timings dict."""
    now = time.time()
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return {}
        if job._last_phase_key and job._last_phase_key in job.phase_timings:
            prev = job.phase_timings[job._last_phase_key]
            if "end" not in prev:
                prev["end"] = now
                prev["duration"] = now - prev["start"]
        return dict(job.phase_timings)


def recreate_job(job_id: str, query: str, depth: str, metadata: dict | None = None) -> JobInfo:
    """Recreate an in-memory JobInfo for resumption after process restart.

    If the job already exists in memory, returns it as-is.
    Otherwise creates a new entry with the given id/query/depth, restoring
    any available metadata (phase timings, study progress, etc.) from GCS.
    """
    with _lock:
        existing = _jobs.get(job_id)
        if existing:
            return existing
        job = JobInfo(job_id=job_id, query=query, depth=depth)
        # Restore rich metadata from GCS if available
        if metadata:
            if metadata.get("created_at"):
                job.created_at = metadata["created_at"]
            if metadata.get("phase_timings"):
                job.phase_timings = metadata["phase_timings"]
            if metadata.get("research_stats"):
                job.research_stats = metadata["research_stats"]
            if metadata.get("study_plan"):
                job.study_plan = metadata["study_plan"]
            if metadata.get("study_progress"):
                job.study_progress = metadata["study_progress"]
            if metadata.get("notebooklm_urls"):
                job.notebooklm_urls = metadata["notebooklm_urls"]
            if metadata.get("elevenlabs_doc_id"):
                job.elevenlabs_doc_id = metadata["elevenlabs_doc_id"]
            if metadata.get("result_url"):
                job.result_url = metadata["result_url"]
            if metadata.get("plan_data"):
                job.plan_data = metadata["plan_data"]
        _jobs[job_id] = job
        return job


def count_active_jobs() -> int:
    """Return the number of jobs currently in PENDING or RUNNING status."""
    with _lock:
        return sum(
            1 for j in _jobs.values()
            if j.status in (JobStatus.PENDING, JobStatus.RUNNING)
        )


def get_running_deep_jobs() -> list[JobInfo]:
    """Return all DEEP jobs currently in RUNNING status."""
    with _lock:
        return [
            j for j in _jobs.values()
            if j.status == JobStatus.RUNNING and j.depth.upper() == "DEEP"
        ]


def request_cancel(job_id: str) -> bool:
    """Request cancellation of a running job. Returns True if the job was found and cancellable."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return False
        if job.status not in (JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PLANNING):
            return False
        job._cancel_requested = True
        job.status = JobStatus.CANCELLING
        return True


def is_cancel_requested(job_id: str) -> bool:
    """Check if cancellation has been requested for a job."""
    with _lock:
        job = _jobs.get(job_id)
        return job._cancel_requested if job else False
