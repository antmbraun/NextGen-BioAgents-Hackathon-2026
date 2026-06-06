from __future__ import annotations

from fda_510k.config import settings
from fda_510k.knowledge.db_510k import Device510kRepository
from fda_510k.models.predicate import PredicateCandidate
from fda_510k.models.profile import SubmissionProfile
from fda_510k.tools.predicate_query import build_predicate_search_query


def _build_rationale(signals: dict[str, float], rec) -> str:
    parts = []
    if signals.get("product_code_match", 0) > 0:
        parts.append(f"matches product code {rec.product_code}")
    if signals.get("name_similarity", 0) > 0.5:
        parts.append("strong device name similarity")
    if signals.get("recency", 0) > 0.5:
        parts.append("relatively recent clearance")
    if signals.get("has_summary", 0) > 0.5:
        parts.append("510(k) Summary available in openFDA")
    if not parts:
        parts.append("metadata similarity from openFDA records")
    return "; ".join(parts)


def _build_risks(rec) -> list[str]:
    risks = []
    if rec.decision_date and rec.decision_date.year < 2010:
        risks.append("Predicate clearance is over 15 years old — verify current SE relevance")
    if rec.decision_code and rec.decision_code != "SESE":
        risks.append(f"Decision code is {rec.decision_code}, not standard SESE")
    if rec.statement_or_summary != "Summary":
        risks.append("Only 510(k) Statement available — limited public detail for SE comparison")
    risks.append("Predicate chain not verified — openFDA lacks structured predicate field")
    return risks


def search_predicates(
    profile: SubmissionProfile,
    repo: Device510kRepository | None = None,
    top_k: int | None = None,
    *,
    search_context: str = "",
) -> list[PredicateCandidate]:
    repo = repo or Device510kRepository()
    top_k = top_k or settings.predicate_top_k

    query_text, product_code, regulation_number = build_predicate_search_query(
        profile,
        search_context=search_context,
    )

    ranked = repo.rank_candidates(
        device_name=query_text or "device",
        product_code=product_code,
        regulation_number=regulation_number,
        top_k=top_k,
    )

    candidates: list[PredicateCandidate] = []
    for rec, score, signals in ranked:
        candidates.append(
            PredicateCandidate(
                k_number=rec.k_number,
                device_name=rec.device_name,
                applicant=rec.applicant,
                product_code=rec.product_code,
                regulation_number=rec.regulation_number,
                device_class=rec.device_class,
                advisory_committee=rec.advisory_committee,
                decision_date=rec.decision_date,
                decision_code=rec.decision_code,
                statement_or_summary=rec.statement_or_summary,
                rank_score=round(score, 3),
                rank_rationale=_build_rationale(signals, rec),
                risks=_build_risks(rec),
                similarity_signals=signals,
            )
        )
    return candidates
