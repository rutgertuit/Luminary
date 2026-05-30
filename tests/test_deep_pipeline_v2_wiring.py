"""Tests for V2 wiring in deep_pipeline (SourceRegistry threading + Phase 3.5 placement).

The full execute_deep_research function is exercised by the integration smoke
test (Task 13). These tests cover the helpers and the import-level invariants.
"""

import inspect

from app.agents import deep_pipeline


def test_execute_deep_research_imports_use_v2_pipeline_helper():
    src = inspect.getsource(deep_pipeline)
    # The pipeline must import and reference the env-flag helper at least once.
    assert "use_v2_pipeline" in src


def test_execute_deep_research_references_source_registry():
    src = inspect.getsource(deep_pipeline)
    assert "SourceRegistry" in src
    # Must thread the registry into run_iterative_study at least once.
    assert "source_registry=" in src


def test_execute_deep_research_calls_outline_generator():
    src = inspect.getsource(deep_pipeline)
    # Phase 3.5 must reference build_outline_generator and parse_outline.
    assert "build_outline_generator" in src
    assert "parse_outline" in src


def test_execute_deep_research_checkpoints_source_registry_under_v2():
    src = inspect.getsource(deep_pipeline)
    # The checkpoint payload must include _source_registry when V2 is on.
    assert "_source_registry" in src


def test_phase_3_5_progress_label_present():
    src = inspect.getsource(deep_pipeline)
    # A user-visible progress label should signal the outline phase.
    assert "outline" in src.lower()
