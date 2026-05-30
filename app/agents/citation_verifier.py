"""Citation verifier (Phase 4.5 of V2 pipeline).

Parses [N] markers in the master synthesis and asks an LLM whether each is
plausibly supported by the corresponding source title + authority + snippet
from the SourceRegistry.
"""

import re

from google.adk.agents import LlmAgent

from app.agents.json_utils import parse_json_response

_CITE_RE = re.compile(r"\[(\d+)\]")


def extract_citation_numbers(text: str) -> list[int]:
    """Return citation numbers found in `text` in first-occurrence order."""
    if not text:
        return []
    seen: list[int] = []
    for m in _CITE_RE.finditer(text):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def parse_audit(raw) -> dict:
    """Parse the verifier's JSON output, filling in defaults for any missing keys."""
    data = parse_json_response(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        return {"unsupported_claims": [], "weak_citations": [], "score": 0}
    data.setdefault("unsupported_claims", [])
    data.setdefault("weak_citations", [])
    data.setdefault("score", 0)
    return data


_VERIFIER_INSTRUCTION = """You are a citation auditor. For the briefing below, check each [N] citation against the corresponding source's title, authority tier, and snippet, and flag any claim that the source does not plausibly support.

Return JSON only:
{
  "unsupported_claims": [
    {"claim": "<exact sentence containing the citation>", "citation_num": <int>, "severity": "high|medium|low", "reason": "<brief>"}
  ],
  "weak_citations": [
    {"citation_num": <int>, "reason": "e.g. LOW AUTHORITY used as sole support for a key claim"}
  ],
  "score": <0-100>
}

Severity guide:
- high: the source clearly does NOT support the claim, or there is no plausible link.
- medium: weak / indirect support, important to flag.
- low: minor mismatch, citation could be improved.

SOURCES:
{reference_block}

BRIEFING:
{synthesis}
"""


def build_citation_verifier(model: str) -> LlmAgent:
    return LlmAgent(
        name="citation_verifier",
        model=model,
        instruction=_VERIFIER_INSTRUCTION,
        output_key="citation_audit_json",
    )


_PATCH_INSTRUCTION = """You are patching a small set of unsupported claims in an executive briefing. Rewrite ONLY the listed claim sentences, using the available references. Do NOT rewrite anything else.

Return JSON only:
{
  "patches": [
    {"original": "<verbatim original sentence>", "replacement": "<rewritten sentence with [N] citation>"}
  ]
}

REFERENCES AVAILABLE:
{reference_block}

UNSUPPORTED CLAIMS TO PATCH:
{claims_block}
"""


def build_patcher(model: str) -> LlmAgent:
    return LlmAgent(
        name="citation_patcher",
        model=model,
        instruction=_PATCH_INSTRUCTION,
        output_key="citation_patches_json",
    )
