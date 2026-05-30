"""Tests for thread-safety of the memory_store module cache."""

import threading

from app.services import memory_store


def _reset_cache():
    with memory_store._cache_lock:
        memory_store._cache["data"] = None
        memory_store._cache["ts"] = 0


def setup_function(_):
    _reset_cache()


def teardown_function(_):
    _reset_cache()


class _FakeBlob:
    def __init__(self, payload):
        self._payload = payload

    def exists(self):
        return True

    def download_as_text(self):
        return self._payload


class _FakeBucket:
    def __init__(self, payload):
        self._payload = payload

    def blob(self, _name):
        return _FakeBlob(self._payload)


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def bucket(self, _name):
        return _FakeBucket(self._payload)


def _install_fake_gcs(monkeypatch, payload, call_count):
    import sys
    import types
    import google  # noqa: F401  — ensure real namespace is loaded

    storage_mod = types.ModuleType("google.cloud.storage")

    def _client_factory():
        call_count["n"] = call_count.get("n", 0) + 1
        return _FakeClient(payload)

    storage_mod.Client = _client_factory

    cloud_mod = types.ModuleType("google.cloud")
    cloud_mod.storage = storage_mod

    monkeypatch.setitem(sys.modules, "google.cloud", cloud_mod)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_mod)


def test_returns_empty_store_for_blank_bucket():
    store = memory_store.load_memory("", use_cache=False)
    assert store.entries == []


def test_cache_populates_and_reuses(monkeypatch):
    payload = '{"entries": [{"id": "abc", "type": "finding", "content": "x"}]}'
    call_count = {"n": 0}
    _install_fake_gcs(monkeypatch, payload, call_count)

    first = memory_store.load_memory("bucket-x")
    second = memory_store.load_memory("bucket-x")
    assert first is second
    assert call_count["n"] == 1
    assert len(first.entries) == 1
    assert first.entries[0].id == "abc"


def test_concurrent_load_is_thread_safe(monkeypatch):
    payload = '{"entries": []}'
    _install_fake_gcs(monkeypatch, payload, {"n": 0})

    results = []
    errors = []

    def worker():
        try:
            results.append(memory_store.load_memory("bucket-y"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == []
    assert len(results) == 10
    assert all(isinstance(r, memory_store.MemoryStore) for r in results)
