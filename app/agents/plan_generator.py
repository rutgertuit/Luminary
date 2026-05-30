"""Plan generator — fast pre-flight analysis that produces a ResearchPlan.

Single LLM call (~10s) that analyzes the user's query and proposes a research
plan with recommended depth, study angles, clarifying questions, and duration estimate.
Replaces the old keyword-based depth detection with intelligent assessment.
"""

import logging
import os

from app.agents.json_utils import parse_json_response
from app.models.research_plan import ResearchPlan

logger = logging.getLogger(__name__)

PLAN_GENERATOR_INSTRUCTION = """You are a research planning assistant. Analyze the user's query and produce a research plan.

Output ONLY valid JSON with this exact structure:
{
  "interpreted_query": "A clearer, more specific version of what the user is asking. Fix typos, resolve ambiguity, add specificity.",
  "recommended_depth": "QUICK or STANDARD or DEEP",
  "depth_reasoning": "One sentence explaining why this depth is appropriate.",
  "domains": ["finance", "technology"],
  "complexity": "low or medium or high",
  "needs_fact_checking": true,
  "controversial": false,
  "proposed_studies": [
    {
      "title": "Study title",
      "angle": "What this study investigates (1 sentence)",
      "questions": ["Specific searchable question 1", "Question 2"],
      "recommended_role": "general"
    }
  ],
  "clarifying_questions": ["Question to ask the user if the query is ambiguous"],
  "estimated_duration": 300
}

DEPTH RULES:
- QUICK (~90s): Simple factual lookups, definitions, quick comparisons. 1 study.
- STANDARD (~5min): Most business questions, market overviews, trend analysis. 2-5 studies.
- DEEP (~20-40min): Complex multi-faceted analysis, strategic decisions, industry deep dives. 4-12 studies.

STUDY PLANNING RULES:
- Each study must explore a DISTINCT angle (don't overlap)
- Each study title should be SHORT and specific (max 10 words) — NOT the full query
- QUICK: exactly 1 study with 1-2 questions
- STANDARD: 2-5 studies with 2-3 questions each
- DEEP: 4-12 studies with 2-4 questions each
- recommended_role: "general", "domain_expert", or "financial_analyst"

IMPORTANT: Break the query into DISTINCT sub-topics. Each study must cover a DIFFERENT aspect.
Do NOT repeat the original query as a study title or question.

CLARIFYING QUESTIONS:
- Only include these if the query is genuinely ambiguous or too vague
- Max 3 questions. Empty list if the query is clear enough.

ESTIMATED DURATION:
- QUICK: 60-90 seconds
- STANDARD: 180-420 seconds (based on number of studies)
- DEEP: 1200-2400 seconds (based on complexity)

No explanation, no markdown fences, just the JSON object."""


_DURATION_ESTIMATES = {
    "QUICK": 90,
    "STANDARD": 300,
    "DEEP": 2400,
}

_MODELS = ["gemini-3.5-flash", "gemini-3.1-pro-preview"]


async def generate_plan(
    query: str,
    context: str = "",
    business_context: dict | None = None,
    model: str = "",
    preferred_depth: str = "",
) -> ResearchPlan:
    """Generate a research plan from a user query. Fast (~5-10s)."""
    from google import genai
    from google.genai.types import GenerateContentConfig

    api_key = os.getenv("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)

    prompt_parts = [f"User's research query: {query}"]
    if preferred_depth:
        prompt_parts.append(
            f"IMPORTANT: The user has explicitly selected {preferred_depth} depth. "
            f"You MUST use recommended_depth=\"{preferred_depth}\" and generate "
            f"the appropriate number of studies for that depth level."
        )
    if context:
        prompt_parts.insert(0, f"Context from past research:\n{context[:2000]}")
    if business_context:
        bc_parts = []
        if business_context.get("user_role"):
            bc_parts.append(f"User role: {business_context['user_role']}")
        if business_context.get("industry"):
            bc_parts.append(f"Industry: {business_context['industry']}")
        if business_context.get("decision_type"):
            bc_parts.append(f"Decision type: {business_context['decision_type']}")
        if business_context.get("stakeholders"):
            bc_parts.append(f"Stakeholders: {business_context['stakeholders']}")
        if bc_parts:
            prompt_parts.append("Business context:\n" + "\n".join(bc_parts))

    prompt = "\n\n".join(prompt_parts)

    # Try each model in order
    models_to_try = [model] if model else _MODELS
    last_error = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=f"{PLAN_GENERATOR_INSTRUCTION}\n\n{prompt}",
                config=GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=4000,
                ),
            )

            text = response.text if response.text else ""
            if not text:
                logger.warning("Plan generator returned empty text with model %s", m)
                continue

            parsed = parse_json_response(text)

            if isinstance(parsed, dict):
                plan = ResearchPlan(
                    original_query=query,
                    interpreted_query=parsed.get("interpreted_query", query),
                    recommended_depth=parsed.get("recommended_depth", "STANDARD").upper(),
                    depth_reasoning=parsed.get("depth_reasoning", ""),
                    domains=parsed.get("domains", []),
                    complexity=parsed.get("complexity", "medium"),
                    needs_fact_checking=parsed.get("needs_fact_checking", False),
                    controversial=parsed.get("controversial", False),
                    proposed_studies=parsed.get("proposed_studies", []),
                    clarifying_questions=parsed.get("clarifying_questions", []),
                    estimated_duration=parsed.get("estimated_duration", _DURATION_ESTIMATES.get(
                        parsed.get("recommended_depth", "STANDARD").upper(), 300
                    )),
                    business_context=business_context or {},
                )

                # Validate depth
                if plan.recommended_depth not in ("QUICK", "STANDARD", "DEEP"):
                    plan.recommended_depth = "STANDARD"

                # Honor user's explicit depth preference
                if preferred_depth and preferred_depth in ("QUICK", "STANDARD", "DEEP"):
                    plan.recommended_depth = preferred_depth
                    plan.estimated_duration = _DURATION_ESTIMATES.get(preferred_depth, plan.estimated_duration)

                logger.info(
                    "Plan generated: depth=%s, studies=%d, clarifying_qs=%d, est=%ds (model=%s)",
                    plan.recommended_depth,
                    len(plan.proposed_studies),
                    len(plan.clarifying_questions),
                    plan.estimated_duration,
                    m,
                )
                return plan

            logger.warning("Plan generator returned non-dict with model %s: %s — raw: %s",
                           m, type(parsed), text[:200])
        except Exception as exc:
            last_error = exc
            logger.warning("Plan generation failed with model %s: %s", m, exc)

    if last_error:
        logger.exception("All plan generation models failed", exc_info=last_error)
    return _fallback_plan(query, preferred_depth, business_context)


def _fallback_plan(query: str, preferred_depth: str = "", business_context: dict | None = None) -> ResearchPlan:
    """Fallback plan when LLM call fails — uses preferred_depth if set."""
    depth = preferred_depth if preferred_depth in ("QUICK", "STANDARD", "DEEP") else "STANDARD"
    return ResearchPlan(
        original_query=query,
        interpreted_query=query,
        recommended_depth=depth,
        depth_reasoning="Plan generated from template (AI analysis unavailable). Edit studies below before starting.",
        domains=[],
        complexity="medium" if depth != "DEEP" else "high",
        proposed_studies=_generate_fallback_studies(query, depth),
        clarifying_questions=[],
        estimated_duration=_DURATION_ESTIMATES.get(depth, 300),
        business_context=business_context or {},
    )


def _generate_fallback_studies(query: str, depth: str) -> list[dict]:
    """Generate sensible fallback studies based on depth."""
    if depth == "QUICK":
        return [{"title": "Quick Overview", "angle": "Key facts and definitions", "questions": [query], "recommended_role": "general"}]

    if depth == "STANDARD":
        return [
            {"title": "Core Concepts", "angle": "Definitions, frameworks, and key terminology", "questions": [f"What are the key concepts in: {query[:100]}?"], "recommended_role": "general"},
            {"title": "Practical Implementation", "angle": "How-to, best practices, and common approaches", "questions": [f"Best practices for: {query[:100]}?"], "recommended_role": "general"},
            {"title": "Challenges & Solutions", "angle": "Common pitfalls and how to overcome them", "questions": [f"Common challenges with: {query[:100]}?"], "recommended_role": "general"},
        ]

    # DEEP
    return [
        {"title": "Foundations & Definitions", "angle": "Core concepts, terminology, and frameworks", "questions": [f"What are the foundational concepts?", f"Key terminology and definitions?"], "recommended_role": "general"},
        {"title": "Technical Architecture", "angle": "Technical components and how they connect", "questions": [f"Technical architecture and components?", f"How do the parts integrate?"], "recommended_role": "domain_expert"},
        {"title": "Implementation Guide", "angle": "Step-by-step implementation and setup", "questions": [f"Implementation steps and requirements?", f"Setup and configuration best practices?"], "recommended_role": "general"},
        {"title": "Data & Integration", "angle": "Data schemas, APIs, and integration patterns", "questions": [f"Data schemas and formats?", f"Integration methods and APIs?"], "recommended_role": "domain_expert"},
        {"title": "Best Practices", "angle": "Industry best practices and optimization strategies", "questions": [f"Industry best practices?", f"Optimization strategies?"], "recommended_role": "general"},
        {"title": "Challenges & Troubleshooting", "angle": "Common problems and their solutions", "questions": [f"Common challenges and pitfalls?", f"Troubleshooting and solutions?"], "recommended_role": "general"},
    ]
