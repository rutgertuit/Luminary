"""Outline generator agent (Phase 3.5 of V2 pipeline).

Produces a structured JSON outline that drives master synthesis.
Falls back to a default outline matching the legacy master-synthesis structure.
"""

from google.adk.agents import LlmAgent

from app.agents.json_utils import parse_json_response


DEFAULT_OUTLINE = {
    "title": "Executive Research Briefing",
    "sections": [
        {"id": "exec_summary", "title": "Executive Summary",
         "target_perspectives": [], "relevant_study_indices": [], "key_questions": []},
        {"id": "study_summaries", "title": "Study Summaries",
         "target_perspectives": [], "relevant_study_indices": [], "key_questions": []},
        {"id": "cross_study", "title": "Cross-Study Analysis",
         "target_perspectives": [], "relevant_study_indices": [], "key_questions": []},
        {"id": "key_findings", "title": "Key Findings & Recommendations",
         "target_perspectives": [], "relevant_study_indices": [], "key_questions": []},
        {"id": "reliability", "title": "Source Reliability Notes",
         "target_perspectives": [], "relevant_study_indices": [], "key_questions": []},
        {"id": "confidence", "title": "Confidence Assessment",
         "target_perspectives": [], "relevant_study_indices": [], "key_questions": []},
    ],
}


def parse_outline(raw) -> dict:
    """Parse the outline JSON or return DEFAULT_OUTLINE on failure.

    Accepts either a string (calls parse_json_response on it) or a dict.
    """
    data = parse_json_response(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict) or not data.get("sections"):
        return DEFAULT_OUTLINE
    return data


_INSTRUCTION = """You are a research-outline planner. Given a research query, a list of stakeholder perspectives, and the syntheses of completed research studies, produce a structured outline for the executive briefing.

Return JSON with this exact shape:
{
  "title": "Executive Research Briefing: <query>",
  "sections": [
    {
      "id": "<short_snake_case_id>",
      "title": "<section title>",
      "target_perspectives": ["<perspective_id>", ...],
      "relevant_study_indices": [<int>, ...],
      "key_questions": ["<question this section answers>", ...]
    }
  ]
}

Rules:
- 5-8 sections, ordered to flow logically.
- Always include an Executive Summary section first and a Confidence Assessment last.
- Every section MUST cite at least one perspective and at least one study index.
- Output JSON only. No prose, no markdown fences.

Inputs:
PERSPECTIVES: {perspectives_json}

STUDY SYNTHESES:
{study_syntheses}
"""


def build_outline_generator(model: str) -> LlmAgent:
    return LlmAgent(
        name="outline_generator",
        model=model,
        instruction=_INSTRUCTION,
        output_key="outline_json",
    )
