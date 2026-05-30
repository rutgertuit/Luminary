"""Tests for the Yahoo Finance crumb-authenticated quote path (tool review F2).

Yahoo's v7 quote endpoint returns 401 without a cookie + crumb. These tests
mock the handshake/HTTP layer so they run offline and assert: the crumb is sent,
a quote is parsed, an expired-crumb 401 triggers exactly one refresh-and-retry,
and a failed handshake degrades to an error dict (not an exception).
"""

import requests

from app.services import financial_client as fc


class _FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


_QUOTE_OK = {"quoteResponse": {"result": [{
    "symbol": "AAPL", "shortName": "Apple Inc.", "regularMarketPrice": 312.06,
    "regularMarketChangePercent": 1.2, "marketCap": 4583336181760,
    "trailingPE": 37.7, "regularMarketVolume": 1000,
}]}}


class _FakeSession:
    """Records the params passed to the quote endpoint and replays queued responses."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.last_params = None

    def get(self, url, params=None, timeout=None):
        self.last_params = params
        return self._responses.pop(0)


def _patch_handshake(monkeypatch, session, crumb="CRUMB123"):
    monkeypatch.setattr(fc, "_yahoo_handshake", lambda force=False: (session, crumb))


def test_yahoo_quote_sends_crumb_and_parses(monkeypatch):
    session = _FakeSession([_FakeResp(200, _QUOTE_OK)])
    _patch_handshake(monkeypatch, session)
    out = fc._yahoo_quote("AAPL")
    assert session.last_params["crumb"] == "CRUMB123"
    assert out["name"] == "Apple Inc."
    assert out["price"] == 312.06
    assert out["market_cap"] == 4583336181760


def test_yahoo_quote_refreshes_crumb_on_401(monkeypatch):
    # First call 401 (expired crumb), retry succeeds.
    session = _FakeSession([_FakeResp(401), _FakeResp(200, _QUOTE_OK)])
    calls = {"n": 0}

    def fake_handshake(force=False):
        calls["n"] += 1
        # force should be True on the retry
        assert force == (calls["n"] == 2)
        return session, "CRUMB"

    monkeypatch.setattr(fc, "_yahoo_handshake", fake_handshake)
    out = fc._yahoo_quote("AAPL")
    assert calls["n"] == 2
    assert out["name"] == "Apple Inc."


def test_yahoo_quote_handshake_failure_returns_error(monkeypatch):
    monkeypatch.setattr(fc, "_yahoo_handshake", lambda force=False: (None, ""))
    out = fc._yahoo_quote("AAPL")
    assert "error" in out
    assert "crumb" in out["error"].lower()


def test_yahoo_quote_empty_result_is_error(monkeypatch):
    session = _FakeSession([_FakeResp(200, {"quoteResponse": {"result": []}})])
    _patch_handshake(monkeypatch, session)
    out = fc._yahoo_quote("ZZZZ")
    assert "error" in out


def test_get_stock_data_uses_alpha_vantage_when_key_present(monkeypatch):
    captured = {}
    monkeypatch.setattr(fc, "_alpha_vantage_overview",
                        lambda t, k: captured.update(ticker=t, key=k) or {"ticker": t})
    monkeypatch.setattr(fc, "_yahoo_quote",
                        lambda t: (_ for _ in ()).throw(AssertionError("should not call Yahoo")))
    fc.get_stock_data("AAPL", api_key="AV_KEY")
    assert captured == {"ticker": "AAPL", "key": "AV_KEY"}
