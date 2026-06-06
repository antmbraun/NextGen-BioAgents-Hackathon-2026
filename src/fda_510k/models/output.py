from __future__ import annotations

from pydantic import BaseModel, Field

from fda_510k.models.gap import GapItem
from fda_510k.models.predicate import PredicateCandidate, SEComparison
from fda_510k.models.profile import SubmissionProfile

DEFAULT_DISCLAIMERS = [
    "Drafting assistant only. Not legal or regulatory advice.",
    "Human regulatory review required before FDA submission.",
    "openFDA data is not legally validated — verify against official FDA records.",
    "All LLM-generated content is marked DRAFT and requires expert review.",
]


class ClarifyingQuestion(BaseModel):
    question: str
    field_id: str
    severity: str
    rationale: str


class EstarDraft(BaseModel):
    estar_section_id: str
    section_label: str
    field_id: str
    content: str
    is_draft: bool = True


class FDAQuestion(BaseModel):
    category: str
    question: str
    risk_level: str
    mitigation: str
    triggered_by: list[str] = Field(default_factory=list)


class SubmissionFieldValue(BaseModel):
    field_id: str
    label: str
    section_id: str
    section_label: str
    content: str
    provenance: str
    confidence: float = 0.0
    requires_review: bool = True


class SubmissionPackage(BaseModel):
    version: str = "nIVD_v6.2"
    readiness_score: float = 0.0
    fields: list[SubmissionFieldValue] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)
    inferred_count: int = 0
    drafted_count: int = 0
    explicit_count: int = 0
    estar_xml: str | None = None
    estar_xml_version: str = "nIVD_v7.0"


class AgentOutput(BaseModel):
    submission_profile: SubmissionProfile
    gap_analysis: list[GapItem] = Field(default_factory=list)
    predicate_candidates: list[PredicateCandidate] = Field(default_factory=list)
    se_comparison: SEComparison | None = None
    estar_drafts: list[EstarDraft] = Field(default_factory=list)
    submission_package: SubmissionPackage | None = None
    anticipated_fda_questions: list[FDAQuestion] = Field(default_factory=list)
    clarifying_questions: list[ClarifyingQuestion] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=lambda: list(DEFAULT_DISCLAIMERS))
