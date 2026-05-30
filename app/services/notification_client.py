"""Notification client - sends alerts when watch changes are detected.

Supports webhook (Slack/Discord/custom) and email (SendGrid) notifications.
"""

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "kubernetes.default",
    "kubernetes.default.svc",
}


class UnsafeWebhookURL(ValueError):
    """Raised when a user-supplied webhook URL points at an internal/unsafe target."""


def _is_safe_webhook_url(url):
    """Validate a user-supplied webhook URL to prevent SSRF."""
    if not url or not isinstance(url, str):
        return False, "empty url"
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return False, f"unparseable url: {exc}"

    if parsed.scheme not in ("http", "https"):
        return False, f"scheme not allowed: {parsed.scheme!r}"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "missing hostname"
    if host in _BLOCKED_HOSTS:
        return False, f"blocked host: {host}"
    if host in ("169.254.169.254", "fd00:ec2::254"):
        return False, "blocked cloud metadata address"

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return False, f"dns resolution failed: {exc}"

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"host resolves to non-public address: {addr}"

    return True, ""


async def send_watch_notification(watch, update) -> None:
    """Send notification when a watch detects changes."""
    if watch.notification_email:
        try:
            await _send_email(watch.notification_email, watch.query, update.summary)
        except Exception:
            logger.exception("Email notification failed for watch %s", watch.id)

    if watch.notification_webhook:
        try:
            await _send_webhook(watch.notification_webhook, watch, update)
        except Exception:
            logger.exception("Webhook notification failed for watch %s", watch.id)


async def _send_email(to: str, subject_topic: str, body: str) -> None:
    api_key = os.getenv("SENDGRID_API_KEY", "")
    if not api_key:
        logger.warning("SendGrid API key not configured, skipping email notification")
        return

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": to}]}],
                "from": {"email": os.getenv("SENDGRID_FROM_EMAIL", "noreply@luminary.app")},
                "subject": f"Luminary Watch Alert: {subject_topic[:80]}",
                "content": [
                    {
                        "type": "text/plain",
                        "value": (
                            f"Changes detected for your research watch:\n\n"
                            f"Topic: {subject_topic}\n\n"
                            f"Summary of changes:\n{body}\n\n"
                            f"- Luminary Research Intelligence"
                        ),
                    }
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Email notification sent to %s for topic: %s", to, subject_topic[:60])


async def _send_webhook(url: str, watch, update) -> None:
    """POST JSON to a webhook URL. Validates URL to prevent SSRF."""
    ok, reason = _is_safe_webhook_url(url)
    if not ok:
        logger.warning(
            "Refusing webhook for watch %s: %s (url=%s)",
            getattr(watch, "id", "?"), reason, (url or "")[:80],
        )
        raise UnsafeWebhookURL(reason)

    payload = {
        "text": f"Luminary Watch Alert: Changes detected for *{watch.query}*",
        "watch_id": watch.id,
        "query": watch.query,
        "changed": update.changed,
        "summary": update.summary,
        "checked_at": update.checked_at,
    }

    async with httpx.AsyncClient(follow_redirects=False) as client:
        resp = await client.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Webhook notification sent to %s for watch %s", url[:60], watch.id)
