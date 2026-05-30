from app.services import research_index as ri


def test_build_entry_extracts_fields():
    entry = ri.build_entry(
        job_id="abc123",
        title="EV battery supply chain",
        depth="DEEP",
        created_at="2026-05-30T10:00:00+00:00",
        summary="x" * 400,
        tags=["ev", "battery"],
    )
    assert entry["job_id"] == "abc123"
    assert entry["title"] == "EV battery supply chain"
    assert entry["depth"] == "DEEP"
    assert len(entry["summary"]) <= 200  # truncated
    assert entry["tags"] == ["ev", "battery"]


def test_upsert_entry_dedupes_by_job_id_newest_first():
    entries = [ri.build_entry("a", "A", "QUICK", "2026-05-01T00:00:00+00:00", "s", [])]
    out = ri.upsert_entry(entries, ri.build_entry("a", "A2", "DEEP", "2026-05-02T00:00:00+00:00", "s2", []))
    assert len(out) == 1
    assert out[0]["title"] == "A2"  # replaced
    out2 = ri.upsert_entry(out, ri.build_entry("b", "B", "QUICK", "2026-05-03T00:00:00+00:00", "s", []))
    assert [e["job_id"] for e in out2] == ["b", "a"]  # newest first


def test_render_index_markdown_lists_entries():
    entries = [ri.build_entry("b", "Topic B", "QUICK", "2026-05-03T00:00:00+00:00", "About B", [])]
    md = ri.render_index_markdown(entries)
    assert "Research Library Index" in md
    assert "Topic B" in md
    assert "b" in md  # job_id referenced


def test_render_index_markdown_empty():
    assert "Research Library Index" in ri.render_index_markdown([])


def test_append_completed_job_loads_upserts_saves(monkeypatch):
    saved = {}
    monkeypatch.setattr(ri, "load_index", lambda bucket: [])
    monkeypatch.setattr(ri, "save_index", lambda entries, bucket: saved.update(entries=entries))
    md = ri.append_completed_job(
        job_id="j1", title="T", depth="DEEP",
        created_at="2026-05-30T00:00:00+00:00", summary="S", tags=["t"],
        bucket="b",
    )
    assert saved["entries"][0]["job_id"] == "j1"
    assert "Research Library Index" in md
    assert "T" in md


def test_append_completed_job_no_bucket_returns_empty(monkeypatch):
    # No bucket → no-op, returns rendered (empty) markdown without raising
    assert "Research Library Index" in ri.append_completed_job(
        "j", "T", "QUICK", "2026-05-30T00:00:00+00:00", "S", [], bucket="")
