from __future__ import annotations

from fda_510k.knowledge.checklist import evaluate_device_conditions, load_estar_checklist
from fda_510k.models.common import FieldProvenance
from fda_510k.output.estar_xml_export import ESTAR_XML_VERSION, export_estar_xml
from fda_510k.models.gap import GapSeverity
from fda_510k.models.output import (
    AgentOutput,
    SubmissionFieldValue,
    SubmissionPackage,
)


def _provenance_from_profile(field) -> tuple[str, float, bool]:
    if field is None or field.value is None:
        return "drafted", 0.0, True
    prov = field.provenance.value
    if prov == "explicit":
        return "explicit", field.confidence, False
    if prov == "inferred":
        return "inferred", field.confidence, True
    return "drafted", field.confidence, True


def build_submission_package(output: AgentOutput) -> SubmissionPackage:
    profile = output.submission_profile
    draft_by_field = {d.field_id: d for d in output.estar_drafts}
    checklist = load_estar_checklist()
    conditions = evaluate_device_conditions(profile)
    fields: list[SubmissionFieldValue] = []
    review_items: list[str] = []
    explicit_count = inferred_count = drafted_count = 0

    for item in checklist:
        if item.condition and not conditions.get(item.condition, False):
            continue
        profile_field = getattr(profile, item.profile_field, None)
        draft = draft_by_field.get(item.id)
        content = draft.content if draft else ""
        if not content and profile_field and profile_field.value is not None:
            if isinstance(profile_field.value, list):
                content = ", ".join(str(v) for v in profile_field.value)
            else:
                content = str(profile_field.value)

        prov, confidence, requires_review = _provenance_from_profile(profile_field)
        if draft and draft.is_draft:
            prov = "drafted"
            requires_review = True
            drafted_count += 1
        elif prov == "explicit":
            explicit_count += 1
        elif prov == "inferred":
            inferred_count += 1
        else:
            drafted_count += 1

        if requires_review:
            review_items.append(f"Verify {item.label} ({item.id}) — {prov}")

        fields.append(
            SubmissionFieldValue(
                field_id=item.id,
                label=item.label,
                section_id=item.section_id,
                section_label=item.section_label,
                content=content or "[Content pending — VERIFY]",
                provenance=prov,
                confidence=confidence,
                requires_review=requires_review,
            )
        )

    for gap in output.gap_analysis:
        if gap.severity == GapSeverity.BLOCKER and gap.status != "present":
            item = f"BLOCKER: {gap.label} — complete before submission"
            if item not in review_items:
                review_items.append(item)

    for pred in output.predicate_candidates[:1]:
        for risk in pred.risks:
            item = f"Predicate {pred.k_number}: {risk}"
            if item not in review_items:
                review_items.append(item)

    filled = sum(1 for f in fields if f.content and f.content != "[Content pending — VERIFY]")
    readiness = filled / len(fields) if fields else 0.0

    package = SubmissionPackage(
        readiness_score=round(readiness, 3),
        fields=fields,
        review_items=review_items,
        explicit_count=explicit_count,
        inferred_count=inferred_count,
        drafted_count=drafted_count,
    )
    output_with_package = output.model_copy(update={"submission_package": package})
    package = package.model_copy(
        update={
            "estar_xml": export_estar_xml(output_with_package, package),
            "estar_xml_version": ESTAR_XML_VERSION,
        }
    )
    return package
