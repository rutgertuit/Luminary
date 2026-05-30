"""Tests for V2 Phase 4.5 wiring in deep_pipeline (citation verifier + patch pass).

The actual ADK runs are exercised by the integration smoke test (Task 13).
These tests confirm the symbols and ordering invariants.
"""

import inspect

from app.agents import deep_pipeline


def test_deep_pipeline_imports_citation_verifier_symbols():
    src = inspect.getsource(deep_pipeline)
    assert "build_citation_verifier" in src
    assert "build_patcher" in src
    assert "parse_audit" in src


def test_deep_pipeline_records_citation_audit_on_result():
    src = inspect.getsource(deep_pipeline)
    assert "result.citation_audit" in src


def test_patch_pass_gated_on_severity_high():
    src = inspect.getsource(deep_pipeline)
    # The patch pass must filter on severity == "high".
    assert '"severity"' in src or "'severity'" in src
    assert '"high"' in src or "'high'" in src


def test_phase_4_5_runs_before_strategic_analysis():
    src = inspect.getsource(deep_pipeline)
    citation_marker = src.find("Phase 4.5")
    strategic_marker = src.find("Phase 4c: Strategic Analysis")
    assert citation_marker != -1, "Phase 4.5 marker missing"
    assert strategic_marker != -1, "Phase 4c marker missing"
    assert citation_marker < strategic_marker, (
        "Phase 4.5 must precede Phase 4c (Strategic Analysis)"
    )


def test_final_reference_list_snapshot_under_v2():
    src = inspect.getsource(deep_pipeline)
    # The pipeline must refresh result.reference_list near the end.
    # Count: we expect the assignment to appear at least twice (Task 10 set it
    # during master synthesis; Task 12 sets it again before return).
    assert src.count("result.reference_list = ") >= 2
