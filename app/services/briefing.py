"""Extract the executive-summary tier of a research result for injection.

This is the text injected as the ``current_research`` dynamic variable at
conversation start — must fit the agent's prompt budget, so it is the
master/final synthesis, never the full study set.
"""
from __future__ import annotations


def extract_executive_summary(result, depth: str) -> str:
    """Return the best executive-summary text for the given depth."""
    master = getattr(result, "master_synthesis", "") or ""
    final = getattr(result, "final_synthesis", "") or ""
    if (depth or "").upper() == "DEEP" and master.strip():
        return master
    if final.strip():
        return final
    # Fallback: whichever is present.
    return master or final
