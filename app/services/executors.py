"""Shared thread-pool executors for offloading blocking I/O from asyncio.

The deep/iterative research pipelines fan out with ``asyncio.gather`` and then
call synchronous HTTP clients (OpenAI, Gemini Deep Research, Grok) via
``loop.run_in_executor``. The default asyncio executor is sized to
``min(32, os.cpu_count() + 4)`` — on a single-vCPU Cloud Run instance that's
only five threads, which can starve when several studies run in parallel.

A dedicated bounded pool keeps the control-plane event loop responsive and
isolates slow HTTP calls from each other. Size is configurable via
``LUMINARY_IO_POOL_SIZE``; default 16 is roughly
``DEEP_MAX_CONCURRENT_STUDIES * 4``.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_IO_POOL: Optional[ThreadPoolExecutor] = None
_IO_POOL_LOCK = Lock()


def _default_pool_size() -> int:
    try:
        n = int(os.getenv("LUMINARY_IO_POOL_SIZE", "16"))
    except ValueError:
        n = 16
    return max(4, min(64, n))


def get_io_executor() -> ThreadPoolExecutor:
    """Return the process-wide blocking-I/O executor, creating it lazily."""
    global _IO_POOL
    if _IO_POOL is not None:
        return _IO_POOL
    with _IO_POOL_LOCK:
        if _IO_POOL is None:
            size = _default_pool_size()
            _IO_POOL = ThreadPoolExecutor(
                max_workers=size,
                thread_name_prefix="luminary-io",
            )
            logger.info("Initialised shared IO executor (max_workers=%d)", size)
    return _IO_POOL


def shutdown_io_executor(wait: bool = False) -> None:
    """Best-effort shutdown for tests / graceful exit."""
    global _IO_POOL
    with _IO_POOL_LOCK:
        pool = _IO_POOL
        _IO_POOL = None
    if pool is not None:
        try:
            pool.shutdown(wait=wait, cancel_futures=True)
        except TypeError:  # Python <3.9 compatibility
            pool.shutdown(wait=wait)
