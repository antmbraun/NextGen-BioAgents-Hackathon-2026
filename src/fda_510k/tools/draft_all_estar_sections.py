from __future__ import annotations

from fda_510k.config import settings
from fda_510k.extraction.prompts.draft_sections import SECTION_DRAFT_SYSTEM, SECTION_DRAFT_USER
from fda_510k.knowledge.checklist import evaluate_device_conditions, load_estar_checklist
from fda_510k.knowledge.estar_transcript import get_estar_guidance
from fda_510k.llm.gemini_client import GeminiClient
from fda_510k.models.common import ExtractedField, FieldProvenance
from fda_510k.models.gap import GapItem
from fda_510k.models.output import EstarDraft
from fda_510k.models.predicate import PredicateCandidate, SEComparison
from fda_510k.models.profile import SubmissionProfile


def _field_content(field: ExtractedField | None) -> str:
    if field is None or field.value is None:
        return ""
    if isinstance(field.value, list):
        return ", ".join(str(v) for v in field.value)
    return str(field.value)


def _template_draft(
    field_id: str,
    label: str,
    profile: SubmissionProfile,
    predicate: PredicateCandidate | None,
    se: SEComparison | None,
) -> str:
    trade = _field_content(profile.device_trade_name) or "[Device Trade Name — VERIFY]"
    common = _field_content(profile.device_common_name) or "medical device"
    indications = _field_content(profile.indications_for_use) or "[Indications for use — VERIFY]"
    principle = _field_content(profile.principle_of_operation) or "[Principle of operation — VERIFY]"
    pred = f"{predicate.device_name} ({predicate.k_number})" if predicate else "[Predicate — VERIFY]"

    templates: dict[str, str] = {
        "applicant_name": (
            f"The applicant/sponsor for {trade} is [Company Name — VERIFY]. "
            "Complete establishment registration information per 21 CFR 807."
        ),
        "contact": (
            "Regulatory contact: [Name, Title, Email, Phone — VERIFY]. "
            "This individual is authorized to communicate with FDA regarding this submission."
        ),
        "submission_type": (
            "This is a Traditional 510(k) premarket notification submitted under section 510(k) "
            f"of the FD&C Act for {trade}."
        ),
        "product_code": (
            f"Primary FDA product code: {_field_content(profile.product_code) or '[Product Code — VERIFY]'}. "
            "Confirm classification via FDA Product Classification Database."
        ),
        "device_trade_name": f"The subject device trade name is {trade}.",
        "device_common_name": f"The device common or generic name is {common}.",
        "principle_of_operation": (
            f"{principle}. The device achieves its intended purpose through established "
            "technology consistent with the predicate device."
        ),
        "materials": (
            "Patient-contacting and non-contacting materials include [list materials — VERIFY]. "
            "Material biocompatibility shall be evaluated per ISO 10993-1 as applicable."
        ),
        "components_accessories": (
            "The device system includes the main unit and accessories as described in the device description. "
            "[List components and accessories — VERIFY]."
        ),
        "model_numbers": "Model/catalog numbers: [List all models — VERIFY].",
        "indications_for_use": indications,
        "user_predicate_mentions": (
            f"The predicate device is {pred}. Substantial equivalence is claimed to this legally "
            "marketed device with the same intended use."
        ),
        "intended_use_population": (
            "Intended patient population: [e.g., adults 18+ — VERIFY]. "
            "Specify any age, weight, or clinical limitations."
        ),
        "contraindications": (
            "Contraindications include [list or state 'None known' if applicable — VERIFY]. "
            "Align with predicate device labeling where appropriate."
        ),
        "risk_analysis": (
            "Risk management per ISO 14971 has been applied. Hazard analysis identifies foreseeable "
            "hazards and mitigations linked to design controls and verification activities. "
            "[Attach hazard analysis — VERIFY]."
        ),
        "design_controls": (
            f"Design controls per 21 CFR 820.30 document design inputs, outputs, review, verification, "
            f"and validation for {trade}. [Reference design history file — VERIFY]."
        ),
        "bench_testing": (
            "Bench and performance testing demonstrates the device meets design specifications. "
            "Testing includes [describe key tests — VERIFY]. Protocols and results to be included as attachments."
        ),
        "biocompatibility": (
            "Biocompatibility evaluation per ISO 10993-1 addresses patient-contacting materials. "
            "Testing matrix and results [to be completed / attached — VERIFY]."
        ),
        "emc": (
            "Electromagnetic compatibility and electrical safety testing per IEC 60601-1 and IEC 60601-1-2 "
            "(or applicable collateral standards) [results attached — VERIFY]."
        ),
        "software_vv": (
            "Software verification and validation per IEC 62304 [Class — VERIFY] includes requirements "
            "traceability, hazard analysis, and testing. SOUP components are identified and evaluated."
        ),
        "clinical_data": (
            "Clinical data are not required for this 510(k) as substantial equivalence is demonstrated "
            "through non-clinical performance data. [Or describe clinical study if applicable — VERIFY]."
        ),
        "cybersecurity_features": (
            "Cybersecurity risk assessment addresses device authentication, update mechanisms, and "
            "threat modeling per FDA cybersecurity guidance. [Document controls — VERIFY]."
        ),
        "ifu_draft": (
            f"Instructions for Use (IFU) for {trade} describe indications, contraindications, warnings, "
            "precautions, and step-by-step use. [Attach draft IFU — VERIFY]."
        ),
        "labeling_draft": (
            "Device labeling includes product labels and packaging with UDI, manufacturer information, "
            "and required symbols per FDA labeling regulations. [Attach draft labels — VERIFY]."
        ),
        "consensus_standards_cited": (
            "Recognized consensus standards applied include ISO 14971, ISO 13485, and device-specific "
            "standards as listed in the standards section. [Complete standards list — VERIFY]."
        ),
        "sterilization": (
            "Sterilization method: [e.g., EtO, gamma — VERIFY]. Validation per ISO 11135/11137 "
            "and SAL 10^-6 where applicable."
        ),
        "shelf_life": (
            "Shelf life / expiration dating supported by [real-time or accelerated aging — VERIFY]. "
            "Package integrity validation included."
        ),
    }

    base = templates.get(
        field_id,
        f"Draft content for {label}. Complete with device-specific verified information for {trade}.",
    )
    if se and field_id == "user_predicate_mentions":
        base += f"\n\nSE narrative excerpt:\n{se.narrative_draft[:500]}"

    return f"{settings.draft_watermark}\n\n{base}"


def _llm_draft_field(
    llm: GeminiClient,
    field_id: str,
    field_label: str,
    section_label: str,
    profile: SubmissionProfile,
    predicate: PredicateCandidate | None,
    known_value: str,
) -> str | None:
    estar_instructions = get_estar_guidance(field_id=field_id, section_label=section_label)
    if not estar_instructions:
        estar_instructions = "No specific eSTAR transcript excerpt available for this field."

    prompt = SECTION_DRAFT_USER.format(
        field_label=field_label,
        section_label=section_label,
        trade_name=_field_content(profile.device_trade_name) or "Unknown",
        common_name=_field_content(profile.device_common_name) or "Unknown",
        indications=_field_content(profile.indications_for_use) or "Not specified",
        principle=_field_content(profile.principle_of_operation) or "Not specified",
        product_code=_field_content(profile.product_code) or "Not specified",
        predicate=f"{predicate.device_name} ({predicate.k_number})" if predicate else "Not specified",
        known_value=known_value or "None",
        eSTAR_instructions=estar_instructions,
    )
    try:
        text = llm.generate(prompt, system=SECTION_DRAFT_SYSTEM, temperature=0.2)
        if text.strip():
            return f"{settings.draft_watermark}\n\n{text.strip()}"
    except Exception:
        pass
    return None


def draft_all_estar_sections(
    profile: SubmissionProfile,
    gaps: list[GapItem],
    *,
    predicate: PredicateCandidate | None = None,
    se: SEComparison | None = None,
    llm: GeminiClient | None = None,
) -> list[EstarDraft]:
    llm = llm or GeminiClient()
    use_llm = llm.is_available()
    conditions = evaluate_device_conditions(profile)
    gap_by_field = {g.field_id: g for g in gaps}
    drafts: list[EstarDraft] = []

    for item in load_estar_checklist():
        if item.condition and not conditions.get(item.condition, False):
            continue

        field: ExtractedField = getattr(profile, item.profile_field, ExtractedField.missing())
        known = _field_content(field)
        gap = gap_by_field.get(item.id)
        status = gap.status if gap else ("present" if known else "missing")

        if status == "present" and field.provenance == FieldProvenance.EXPLICIT and known:
            content = f"{known}\n\n(Source: user-provided material)"
        elif known and status != "missing":
            content = known
        elif use_llm:
            content = _llm_draft_field(
                llm, item.id, item.label, item.section_label, profile, predicate, known
            )
            if not content:
                content = _template_draft(item.id, item.label, profile, predicate, se)
        else:
            content = _template_draft(item.id, item.label, profile, predicate, se)

        drafts.append(
            EstarDraft(
                estar_section_id=item.section_id,
                section_label=item.section_label,
                field_id=item.id,
                content=content,
                is_draft=status != "present" or field.provenance != FieldProvenance.EXPLICIT,
            )
        )

    return drafts
