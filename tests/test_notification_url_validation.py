"""Tests for the SSRF guard in app.services.notification_client."""

from unittest.mock import patch

from app.services.notification_client import _is_safe_webhook_url


def _force_resolve(addr: str):
    """Patch socket.getaddrinfo to return a single IPv4 address."""
    return patch(
        "app.services.notification_client.socket.getaddrinfo",
        return_value=[(0, 0, 0, "", (addr, 0))],
    )


def test_rejects_empty():
    ok, reason = _is_safe_webhook_url("")
    assert not ok
    assert "empty" in reason


def test_rejects_non_http_scheme():
    ok, reason = _is_safe_webhook_url("ftp://example.com/hook")
    assert not ok
    assert "scheme" in reason


def test_rejects_file_scheme():
    ok, reason = _is_safe_webhook_url("file:///etc/passwd")
    assert not ok


def test_rejects_missing_host():
    ok, reason = _is_safe_webhook_url("http:///path")
    assert not ok


def test_rejects_localhost_by_name():
    ok, reason = _is_safe_webhook_url("http://localhost/hook")
    assert not ok
    assert "localhost" in reason


def test_rejects_gcp_metadata():
    ok, reason = _is_safe_webhook_url("http://metadata.google.internal/compute")
    assert not ok


def test_rejects_aws_metadata_literal():
    ok, reason = _is_safe_webhook_url("http://169.254.169.254/latest/meta-data/")
    assert not ok
    assert "metadata" in reason


def test_rejects_private_ipv4():
    with _force_resolve("10.0.0.5"):
        ok, reason = _is_safe_webhook_url("https://intranet.example/hook")
    assert not ok
    assert "non-public" in reason


def test_rejects_loopback_resolution():
    with _force_resolve("127.0.0.1"):
        ok, reason = _is_safe_webhook_url("https://spoof.example/hook")
    assert not ok
    assert "non-public" in reason


def test_accepts_public_address():
    with _force_resolve("93.184.216.34"):  # example.com
        ok, reason = _is_safe_webhook_url("https://example.com/hook")
    assert ok, reason
    assert reason == ""


def test_accepts_slack_style_url():
    with _force_resolve("52.84.10.20"):  # pretend CDN address
        ok, reason = _is_safe_webhook_url(
            "https://hooks.slack.com/services/T0/B0/xxx"
        )
    assert ok, reason
