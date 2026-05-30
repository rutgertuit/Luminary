"""Data model for a research plan — the pre-flight analysis shown to the user before execution."""

import dataclasses
from dataclasses import dataclass, field


@dataclass
class ResearchPlan:
    """Proposed research plan returned by the plan endpoint.

    The user reviews, optionally edits, then confirms before research executes.
    """
    # Original user input
    original_query: str = ""

    # LLM-interpreted version of the query (clearer, more specific)
    interpreted_query: str = ""

    # Recommended depth with reasoning
    recommended_depth: str = "STANDARD"  # QUICK / STANDARD / DEEP
    depth_reasoning: str = ""

    # Query analysis metadata
    domains: list[str] = field(default_factory=list)
    complexity: str = "medium"  # low / medium / high
    needs_fact_checking: bool = False
    controversial: bool = False

    # Proposed study angles (for STANDARD/DEEP)
    proposed_studies: list[dict] = field(default_factory=list)
    # Each: {title, angle, questions: [...], recommended_role}

    # Clarifying questions the system wants answered before proceeding
    clarifying_questions: list[str] = field(default_factory=list)

    # Estimated duration in seconds
    estimated_duration: int = 300

    # Whether the system recommends auto-proceeding (no confirmation needed)
    auto_proceed: bool = False
    auto_proceed_reason: str = ""

    # Business context (if provided by user)
    business_context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchPlan":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
