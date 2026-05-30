import io
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io/v1"


class RagIndexNotReadyError(Exception):
    """Raised when ElevenLabs rejects an operation because RAG indexing is in progress."""


def _headers(api_key: str) -> dict:
    return {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }


def get_conversation(conversation_id: str, api_key: str) -> dict:
    """Fetch full conversation data from ElevenLabs."""
    url = f"{BASE_URL}/convai/conversations/{conversation_id}"
    resp = requests.get(url, headers=_headers(api_key), timeout=30)
    resp.raise_for_status()
    return resp.json()


def format_conversation_context(data: dict) -> str:
    """Format conversation data into a human-readable transcript."""
    lines = []
    transcript = data.get("transcript", [])
    for turn in transcript:
        role = turn.get("role", "unknown").capitalize()
        message = turn.get("message", "")
        lines.append(f"{role}: {message}")
    return "\n".join(lines)


def upload_to_knowledge_base(text: str, name: str, api_key: str) -> str:
    """Upload markdown as a .md file to ElevenLabs Knowledge Base. Returns document ID."""
    url = f"{BASE_URL}/convai/knowledge-base"
    # Ensure name ends with .md for ElevenLabs to process as markdown
    filename = name if name.endswith(".md") else f"{name}.md"
    md_bytes = text.encode("utf-8")
    files = {"file": (filename, io.BytesIO(md_bytes), "text/markdown")}
    # Use multipart form data — no Content-Type header (requests sets boundary)
    headers = {"xi-api-key": api_key}
    resp = requests.post(url, headers=headers, files=files, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    doc_id = result.get("id", result.get("document_id", ""))
    logger.info("Uploaded KB document (md): %s (id=%s)", name, doc_id)
    return doc_id


_RESEARCH_PREFIXES = ("Research:", "Study:", "Master Briefing:", "Q&A:", "Anticipated Q&A:", "Amendment:")

# Docs that must never be evicted by enforce_kb_limit, regardless of naming —
# e.g. the always-on Research Library Index.
_PINNED_KB_NAMES = ("Research Library Index",)


def enforce_kb_limit(agent_id: str, api_key: str, max_docs: int = 3) -> list[str]:
    """Evict oldest research KB docs so the agent keeps at most *max_docs*.

    Only docs whose name starts with a known research prefix are counted and
    evicted.  The KB list order from ElevenLabs reflects insertion order, so
    earlier entries are treated as oldest.

    Returns the list of evicted document IDs.
    """
    if max_docs < 1:
        return []

    kb = list_agent_knowledge_base(agent_id, api_key)
    research_docs = [
        d for d in kb
        if any(d.get("name", "").startswith(p) for p in _RESEARCH_PREFIXES)
        and not any(d.get("name", "").startswith(p) for p in _PINNED_KB_NAMES)
    ]

    if len(research_docs) <= max_docs:
        return []

    to_evict = research_docs[: len(research_docs) - max_docs]
    evicted_ids = []
    for doc in to_evict:
        did = doc.get("id", doc.get("document_id", ""))
        if not did:
            continue
        try:
            detach_document_from_agent(agent_id, did, api_key)
            evicted_ids.append(did)
        except Exception:
            logger.exception("Failed to evict doc %s from agent %s", did, agent_id)

    if evicted_ids:
        logger.info(
            "Evicted %d old research docs from agent %s to stay within limit %d",
            len(evicted_ids), agent_id, max_docs,
        )
    return evicted_ids


def attach_document_to_agent(agent_id: str, doc_id: str, doc_name: str, api_key: str) -> None:
    """Attach a KB document to an agent using GET-then-PATCH to preserve existing docs."""
    headers = _headers(api_key)

    # GET current agent config
    get_url = f"{BASE_URL}/convai/agents/{agent_id}"
    resp = requests.get(get_url, headers=headers, timeout=30)
    resp.raise_for_status()
    agent_config = resp.json()

    # Extract existing knowledge base docs
    convai_config = agent_config.get("conversation_config", {})
    agent_section = convai_config.get("agent", {})
    prompt_section = agent_section.get("prompt", {})
    existing_kb = prompt_section.get("knowledge_base", [])

    # Check if document is already attached
    existing_ids = {doc.get("id", doc.get("document_id", "")) for doc in existing_kb}
    if doc_id in existing_ids:
        logger.info("Document %s already attached to agent %s", doc_id, agent_id)
        return

    # Detect the type used by existing entries (ElevenLabs may use "file" for all uploads)
    doc_type = "file"
    if existing_kb:
        first_type = existing_kb[0].get("type", "file")
        if first_type in ("file", "text", "url", "folder"):
            doc_type = first_type if first_type == "text" else "file"

    # Append new document
    existing_kb.append({"type": doc_type, "id": doc_id, "name": doc_name})

    # PATCH agent with updated knowledge base
    patch_url = f"{BASE_URL}/convai/agents/{agent_id}"
    patch_payload = {
        "conversation_config": {
            "agent": {
                "prompt": {
                    "knowledge_base": existing_kb,
                }
            }
        }
    }
    logger.info(
        "Patching agent %s KB: adding doc %s (type=%s), total KB entries: %d",
        agent_id, doc_id, doc_type, len(existing_kb),
    )
    resp = requests.patch(patch_url, headers=headers, json=patch_payload, timeout=30)
    if resp.status_code == 422 and "rag_index_not_ready" in resp.text:
        # Auto-fix: trigger both RAG index models and retry
        logger.warning(
            "RAG index not ready for doc %s on agent %s — triggering indexes and polling",
            doc_id, agent_id,
        )
        trigger_all_rag_indexes(doc_id, api_key)
        # Wait up to 180s for indexes to complete. Uses a monotonic deadline so
        # a stalled HTTP call can't blow past the wall-clock budget and hold a
        # worker thread indefinitely.
        indexes_ready = False
        RAG_POLL_BUDGET_S = 180.0
        RAG_POLL_INTERVAL_S = 5.0
        RAG_REQUEST_TIMEOUT_S = 10  # tighter than 30s so stalls exit faster
        deadline = time.monotonic() + RAG_POLL_BUDGET_S
        attempt = 0
        while time.monotonic() < deadline:
            time.sleep(RAG_POLL_INTERVAL_S)
            if time.monotonic() >= deadline:
                break
            attempt += 1
            try:
                idx_resp = requests.get(
                    f"{BASE_URL}/convai/knowledge-base/{doc_id}/rag-index",
                    headers=headers, timeout=RAG_REQUEST_TIMEOUT_S,
                )
            except requests.RequestException as exc:
                logger.warning(
                    "RAG index poll attempt %d for doc %s failed: %s",
                    attempt, doc_id, exc,
                )
                continue
            if idx_resp.ok:
                indexes = idx_resp.json().get("indexes", [])
                statuses = {i.get("model", "?"): i.get("status", "?") for i in indexes}
                if attempt % 6 == 1:  # Log every ~30s
                    logger.info(
                        "RAG index poll %d for doc %s: %s",
                        attempt, doc_id, statuses,
                    )
                if indexes and all(i.get("status") == "succeeded" for i in indexes):
                    logger.info(
                        "All RAG indexes ready for doc %s after ~%.0fs",
                        doc_id, attempt * RAG_POLL_INTERVAL_S,
                    )
                    indexes_ready = True
                    break
        if not indexes_ready:
            logger.warning(
                "RAG indexes still not ready after %.0fs for doc %s (attempts=%d)",
                RAG_POLL_BUDGET_S, doc_id, attempt,
            )
        # Retry the PATCH
        resp = requests.patch(patch_url, headers=headers, json=patch_payload, timeout=30)

    if not resp.ok:
        body = resp.text[:500]
        logger.error(
            "PATCH agent %s failed (%s): %s",
            agent_id, resp.status_code, body,
        )
        if resp.status_code == 422 and "rag_index_not_ready" in body:
            raise RagIndexNotReadyError(
                f"Document {doc_id} is still being indexed by ElevenLabs. "
                "Please try again in a few minutes."
            )
    resp.raise_for_status()
    # Verify the doc was actually added
    verify_resp = requests.get(get_url, headers=headers, timeout=30)
    if verify_resp.ok:
        verify_kb = (
            verify_resp.json()
            .get("conversation_config", {})
            .get("agent", {})
            .get("prompt", {})
            .get("knowledge_base", [])
        )
        verify_ids = {d.get("id", d.get("document_id", "")) for d in verify_kb}
        if doc_id in verify_ids:
            logger.info("Verified: document %s attached to agent %s (KB size: %d)", doc_id, agent_id, len(verify_kb))
        else:
            logger.error(
                "ATTACH FAILED SILENTLY: doc %s not found in agent %s KB after PATCH. "
                "KB types: %s",
                doc_id, agent_id,
                [d.get("type") for d in verify_kb],
            )
    else:
        logger.warning("Could not verify attachment (GET returned %s)", verify_resp.status_code)


def list_agent_knowledge_base(agent_id: str, api_key: str) -> list[dict]:
    """Return the knowledge_base array from an agent's config."""
    url = f"{BASE_URL}/convai/agents/{agent_id}"
    resp = requests.get(url, headers=_headers(api_key), timeout=30)
    resp.raise_for_status()
    agent_config = resp.json()
    kb = (
        agent_config
        .get("conversation_config", {})
        .get("agent", {})
        .get("prompt", {})
        .get("knowledge_base", [])
    )
    if kb:
        logger.info(
            "Agent %s KB: %d entries, types=%s, sample=%s",
            agent_id, len(kb),
            [d.get("type") for d in kb[:3]],
            {k: v for k, v in kb[0].items() if k != "name"}
        )
    return kb


def detach_document_from_agent(agent_id: str, doc_id: str, api_key: str) -> None:
    """Remove a KB document from an agent (GET current list, filter, PATCH back)."""
    headers = _headers(api_key)
    url = f"{BASE_URL}/convai/agents/{agent_id}"

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    agent_config = resp.json()

    existing_kb = (
        agent_config
        .get("conversation_config", {})
        .get("agent", {})
        .get("prompt", {})
        .get("knowledge_base", [])
    )

    filtered = [d for d in existing_kb if d.get("id", d.get("document_id", "")) != doc_id]
    if len(filtered) == len(existing_kb):
        logger.info("Document %s not found on agent %s, nothing to detach", doc_id, agent_id)
        return

    patch_payload = {
        "conversation_config": {
            "agent": {
                "prompt": {
                    "knowledge_base": filtered,
                }
            }
        }
    }
    resp = requests.patch(url, headers=headers, json=patch_payload, timeout=30)
    resp.raise_for_status()
    logger.info("Detached document %s from agent %s", doc_id, agent_id)


def attach_documents_to_agent(agent_id: str, doc_map: dict[str, str], api_key: str) -> None:
    """Attach multiple KB documents to an agent in a single GET + PATCH.

    Args:
        agent_id: ElevenLabs agent ID.
        doc_map: Mapping of document ID to document name.
        api_key: ElevenLabs API key.
    """
    if not doc_map:
        return

    headers = _headers(api_key)

    get_url = f"{BASE_URL}/convai/agents/{agent_id}"
    resp = requests.get(get_url, headers=headers, timeout=30)
    resp.raise_for_status()
    agent_config = resp.json()

    convai_config = agent_config.get("conversation_config", {})
    agent_section = convai_config.get("agent", {})
    prompt_section = agent_section.get("prompt", {})
    existing_kb = prompt_section.get("knowledge_base", [])

    existing_ids = {doc.get("id", doc.get("document_id", "")) for doc in existing_kb}

    # Detect the type used by existing entries
    doc_type = "file"
    if existing_kb:
        first_type = existing_kb[0].get("type", "file")
        if first_type in ("file", "text", "url", "folder"):
            doc_type = first_type if first_type == "text" else "file"

    new_docs = [{"type": doc_type, "id": did, "name": dname} for did, dname in doc_map.items() if did not in existing_ids]

    if not new_docs:
        logger.info("All %d documents already attached to agent %s", len(doc_map), agent_id)
        return

    existing_kb.extend(new_docs)

    patch_url = f"{BASE_URL}/convai/agents/{agent_id}"
    patch_payload = {
        "conversation_config": {
            "agent": {
                "prompt": {
                    "knowledge_base": existing_kb,
                }
            }
        }
    }
    resp = requests.patch(patch_url, headers=headers, json=patch_payload, timeout=30)

    if resp.status_code == 422 and "rag_index_not_ready" in resp.text:
        logger.warning(
            "RAG index not ready for batch attach to agent %s — triggering indexes for %d docs",
            agent_id, len(new_docs),
        )
        for doc in new_docs:
            trigger_all_rag_indexes(doc["id"], api_key)
        # Poll all docs for up to 180s
        for attempt in range(36):
            time.sleep(5)
            all_ready = True
            for doc in new_docs:
                idx_resp = requests.get(
                    f"{BASE_URL}/convai/knowledge-base/{doc['id']}/rag-index",
                    headers=headers, timeout=30,
                )
                if idx_resp.ok:
                    indexes = idx_resp.json().get("indexes", [])
                    if not all(i.get("status") == "succeeded" for i in indexes):
                        all_ready = False
                        break
                else:
                    all_ready = False
                    break
            if all_ready:
                logger.info("All RAG indexes ready after %ds, retrying batch PATCH", (attempt + 1) * 5)
                break
            if attempt % 6 == 0:
                logger.info("RAG index batch poll %d/36 — still waiting", attempt + 1)
        resp = requests.patch(patch_url, headers=headers, json=patch_payload, timeout=30)

    if resp.status_code == 422 and "rag_index_not_ready" in resp.text:
        raise RagIndexNotReadyError(
            f"Documents still being indexed after 180s for agent {agent_id}"
        )
    resp.raise_for_status()
    logger.info("Attached %d new documents to agent %s (total KB: %d)", len(new_docs), agent_id, len(existing_kb))


_RAG_MODELS = ["multilingual_e5_large_instruct", "e5_mistral_7b_instruct"]


def trigger_rag_index(doc_id: str, api_key: str, model: str = "multilingual_e5_large_instruct") -> dict:
    """Trigger RAG indexing for a KB document. Returns index status.

    If already indexed, returns current status without re-indexing.
    """
    url = f"{BASE_URL}/convai/knowledge-base/{doc_id}/rag-index"
    resp = requests.post(url, headers=_headers(api_key), json={"model": model}, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    logger.info("RAG index for doc %s: status=%s", doc_id, result.get("status", "unknown"))
    return result


def trigger_all_rag_indexes(doc_id: str, api_key: str) -> list[dict]:
    """Trigger both RAG index models required for agent attachment.

    ElevenLabs requires both multilingual_e5_large_instruct AND
    e5_mistral_7b_instruct indexes to be ready before a doc can be
    attached to an agent via PATCH.
    """
    results = []
    for model in _RAG_MODELS:
        try:
            r = trigger_rag_index(doc_id, api_key, model=model)
            results.append(r)
        except Exception:
            logger.exception("Failed to trigger RAG index model %s for doc %s", model, doc_id)
    return results
