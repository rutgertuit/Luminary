"""Regression guards for two deep_pipeline defects found in the 2026-05-30 tool review.

F1: strategic analysis was passed the pipeline-default Flash MODEL, silently
    bypassing the router's `gemini_pro` routing for that phase.
F3: the study semaphore `sem` was defined only inside the Phase-2 else-branch, so
    resuming a job with all studies restored then triggering a refinement gap
    study raised `NameError: sem`.

These follow the source-invariant style used by test_deep_pipeline_v2_wiring.py
because the full execute_deep_research function is exercised by the integration
smoke test, not a unit test.
"""

import inspect

from app.agents import deep_pipeline


def _src():
    return inspect.getsource(deep_pipeline)


# ---- F1: strategic analysis must use the router, not the Flash MODEL ----

def test_strategic_analysis_routes_via_model_router():
    src = _src()
    assert 'get_model_for_phase("strategic_analysis")' in src, (
        "Phase 4c must resolve its model from the router (gemini_pro), "
        "not pass the pipeline-default Flash MODEL."
    )


def test_strategic_analysis_does_not_pass_bare_flash_model():
    src = _src()
    # The run_strategic_analysis call must not regress to `model=MODEL`.
    call_idx = src.index("run_strategic_analysis(")
    call_block = src[call_idx:call_idx + 400]
    assert "model=MODEL" not in call_block, (
        "run_strategic_analysis must not be called with the Flash MODEL; "
        "use the router-resolved strategic_model."
    )
    assert "model=strategic_model" in call_block


# ---- F3: the study semaphore must exist even when all studies are restored ----

def test_study_semaphore_defined_at_function_scope():
    src = _src()
    sem_def = "    sem = asyncio.Semaphore(MAX_CONCURRENT_STUDIES)"
    assert sem_def in src, (
        "`sem` must be defined at 4-space (function) indentation so it is in "
        "scope for the refinement gap studies even when Phase 2 is skipped."
    )
    sem_idx = src.index(sem_def)
    # Must be defined before the all-studies-restored skip branch, otherwise the
    # else-branch (which used to own it) is skipped and `sem` is unbound.
    skip_idx = src.index("all %d studies restored from checkpoint")
    assert sem_idx < skip_idx, (
        "`sem` must be defined before the all-restored skip branch."
    )


def test_study_semaphore_not_redefined_inside_else_branch():
    src = _src()
    # Exactly one definition of the study semaphore (the hoisted one).
    assert src.count("sem = asyncio.Semaphore(MAX_CONCURRENT_STUDIES)") == 1
