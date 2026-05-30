"""Tests for the shared blocking-IO executor."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.services import executors


def setup_function(_):
    # Reset between tests so env-var overrides take effect.
    executors.shutdown_io_executor(wait=True)


def teardown_function(_):
    executors.shutdown_io_executor(wait=True)


def test_get_executor_is_singleton():
    a = executors.get_io_executor()
    b = executors.get_io_executor()
    assert a is b
    assert isinstance(a, ThreadPoolExecutor)


def test_executor_size_respects_env(monkeypatch):
    monkeypatch.setenv("LUMINARY_IO_POOL_SIZE", "8")
    pool = executors.get_io_executor()
    assert pool._max_workers == 8


def test_executor_size_clamped(monkeypatch):
    monkeypatch.setenv("LUMINARY_IO_POOL_SIZE", "9999")
    pool = executors.get_io_executor()
    assert pool._max_workers == 64  # clamped to 64


def test_executor_size_min_floor(monkeypatch):
    monkeypatch.setenv("LUMINARY_IO_POOL_SIZE", "1")
    pool = executors.get_io_executor()
    assert pool._max_workers == 4  # clamped to 4


def test_executor_size_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("LUMINARY_IO_POOL_SIZE", "not-a-number")
    pool = executors.get_io_executor()
    assert pool._max_workers == 16


def test_executor_runs_work():
    pool = executors.get_io_executor()
    fut = pool.submit(lambda: 21 * 2)
    assert fut.result(timeout=5) == 42


def test_executor_concurrent_submit_does_not_deadlock(monkeypatch):
    """Submit many blocking tasks; they should all complete without hanging."""
    monkeypatch.setenv("LUMINARY_IO_POOL_SIZE", "8")
    pool = executors.get_io_executor()
    gate = threading.Event()

    def blocker():
        gate.wait(timeout=5)
        return "done"

    futures = [pool.submit(blocker) for _ in range(20)]
    # Let them all block briefly, then release.
    time.sleep(0.1)
    gate.set()
    for f in futures:
        assert f.result(timeout=5) == "done"
