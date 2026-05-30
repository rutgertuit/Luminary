import dataclasses
from dataclasses import dataclass, field


@dataclass
class StudyResult:
    title: str = ""
    angle: str = ""
    questions: list[str] = field(default_factory=list)
    rounds: list[dict[str, str]] = field(default_factory=list)
    synthesis: str = ""
    doc_id: str = ""

    # V2 pipeline additions
    source_floor: int = 8
    compressed_findings: dict[str, str] = field(default_factory=dict)


@dataclass
class QAClusterResult:
    theme: str = ""
    questions: list[str] = field(default_factory=list)
    findings: str = ""
    doc_id: str = ""


@dataclass
class ResearchResult:
    original_query: str = ""

    # STANDARD / QUICK fields (backward compatible)
    unpacked_questions: list[str] = field(default_factory=list)
    research_findings: dict[str, str] = field(default_factory=dict)
    follow_up_questions: list[str] = field(default_factory=list)
    follow_up_findings: dict[str, str] = field(default_factory=dict)
    final_synthesis: str = ""

    # DEEP fields
    study_plan: list[dict] = field(default_factory=list)
    studies: list[StudyResult] = field(default_factory=list)
    master_synthesis: str = ""
    master_doc_id: str = ""
    qa_clusters: list[QAClusterResult] = field(default_factory=list)
    qa_summary: str = ""
    qa_summary_doc_id: str = ""
    all_doc_ids: list[str] = field(default_factory=list)

    # Strategic analysis (populated by strategic analyst)
    strategic_analysis: str = ""

    # Query analysis (populated by query_analyzer in Phase 0)
    query_analysis: dict = field(default_factory=dict)

    # Claim validation (populated by claim_validator after synthesis)
    claim_validation: dict = field(default_factory=dict)

    # NotebookLM source URLs (individual MD files on GCS)
    notebooklm_urls: list[dict] = field(default_factory=list)

    # Synthesis quality (populated by synthesis evaluator)
    synthesis_score: float = 0.0
    synthesis_scores: dict = field(default_factory=dict)
    refinement_rounds: int = 0

    # V2 pipeline additions
    perspectives: list[dict] = field(default_factory=list)
    outline: dict = field(default_factory=dict)
    reference_list: list[dict] = field(default_factory=list)
    citation_audit: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchResult":
        data = dict(data)
        known_study_fields = {f.name for f in dataclasses.fields(StudyResult)}
        known_qa_fields = {f.name for f in dataclasses.fields(QAClusterResult)}
        known_result_fields = {f.name for f in dataclasses.fields(cls)}

        raw_studies = data.pop("studies", [])
        studies = [
            StudyResult(**{k: v for k, v in s.items() if k in known_study_fields})
            for s in raw_studies
        ]
        raw_qa = data.pop("qa_clusters", [])
        qa_clusters = [
            QAClusterResult(**{k: v for k, v in q.items() if k in known_qa_fields})
            for q in raw_qa
        ]
        filtered = {k: v for k, v in data.items() if k in known_result_fields}
        return cls(studies=studies, qa_clusters=qa_clusters, **filtered)
