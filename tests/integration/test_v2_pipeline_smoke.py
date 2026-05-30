"""Smoke test: run a tiny DEEP query through the V2 pipeline against the real Gemini API.

Skipped unless RUN_V2_SMOKE=1 (and the necessary API keys are set in the environment).
"""

import asyncio
import os
import re

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_V2_SMOKE", "") != "1",
    reason="Set RUN_V2_SMOKE=1 (and GOOGLE_API_KEY) to run the live V2 smoke test.",
)


def test_v2_pipeline_smoke(monkeypatch):
    monkeypatch.setenv("LUMINARY_V2_PIPELINE", "1")
    from app.agents.deep_pipeline import execute_deep_research

    result = asyncio.run(execute_deep_research(
        query="What are the main risks of overhead power lines in the Netherlands?",
        max_studies=2,
        max_rounds_per_study=1,
        max_qa_rounds=1,
    ))

    assert result.perspectives, "expected perspectives to be populated under V2"
    assert result.outline.get("sections"), "expected outline.sections to be populated under V2"
    assert result.reference_list, "expected reference_list to be populated under V2"

    # Every [N] in the synthesis must resolve to a registered reference number.
    ref_nums = {r["n"] for r in result.reference_list}
    cited = {int(m.group(1)) for m in re.finditer(r"\[(\d+)\]", result.master_synthesis or "")}
    unresolved = cited - ref_nums
    assert not unresolved, f"unresolved citations: {unresolved}"

    # Citation audit must be populated, even if empty.
    assert "score" in result.citation_audit
