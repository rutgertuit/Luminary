import app.services.elevenlabs_client as el


def test_index_doc_is_not_evicted(monkeypatch):
    # KB has the pinned index + 5 research docs; max_docs=3 → evict 2 research,
    # never the index. Name the index with a research prefix to prove the pin
    # guard (not just the prefix mismatch) protects it.
    kb = [{"id": "idx", "name": "Research Library Index"}] + [
        {"id": f"d{i}", "name": f"Research: topic {i}"} for i in range(5)
    ]
    monkeypatch.setattr(el, "list_agent_knowledge_base", lambda aid, key: kb)
    detached = []
    monkeypatch.setattr(el, "detach_document_from_agent",
                        lambda aid, did, key: detached.append(did))
    el.enforce_kb_limit("agent", "key", max_docs=3)
    assert "idx" not in detached          # index never evicted
    assert len(detached) == 2             # 5 research docs trimmed to 3
