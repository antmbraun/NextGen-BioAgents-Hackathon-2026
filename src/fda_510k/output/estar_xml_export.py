from __future__ import annotations

import re

from fda_510k.knowledge.estar_transcript import load_estar_xml_template
from fda_510k.models.output import AgentOutput, SubmissionPackage

ESTAR_XML_VERSION = "nIVD_v7.0"

# Maps internal checklist field IDs to eSTAR XML element tags in nIVD_eSTAR_7-0_data.xml.
FIELD_TO_XML_TAGS: dict[str, list[str]] = {
    "applicant_name": ["ADTextField210"],
    "contact": ["ADTextField160", "ADTextField190"],
    "submission_type": ["ATTextField135"],
    "product_code": ["DDTextField517a", "DDTextField506"],
    "device_trade_name": ["TradeName"],
    "device_common_name": ["IUTextField120"],
    "principle_of_operation": ["DDTextField400"],
    "materials": ["DDTextField235"],
    "components_accessories": ["DDTextField605"],
    "model_numbers": ["Model"],
    "indications_for_use": ["IUTextField141"],
    "user_predicate_mentions": ["ADTextField830", "ADTextField840"],
    "intended_use_population": ["IUTextField130"],
    "contraindications": ["LBTextField110"],
    "risk_analysis": ["SCTextField100"],
    "design_controls": ["DCTextField110"],
    "bench_testing": ["PTTextField310"],
    "biocompatibility": ["BCTextField911"],
    "emc": ["EMTextField160"],
    "software_vv": ["QMTextField905"],
    "clinical_data": ["PTTextField510"],
    "cybersecurity_features": ["CSTextField440"],
    "ifu_draft": ["LBTextField202"],
    "labeling_draft": ["LBTextField170"],
    "consensus_standards_cited": ["DDTextField610"],
    "sterilization": ["STTextField110"],
    "shelf_life": ["SLTextField110"],
}

SE_XML_TAGS = ["ADTextField870", "ADTextField880"]


def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inject_xml_text(xml: str, tag: str, text: str) -> str:
    if not text or not text.strip():
        return xml
    escaped = _escape_xml(text.strip())
    pattern = rf"<{re.escape(tag)}(\s*\n?\s*)/>"
    if not re.search(pattern, xml):
        return xml
    return re.sub(pattern, rf"<{tag}\1>{escaped}</{tag}>", xml, count=1)


def _field_content_by_id(package: SubmissionPackage) -> dict[str, str]:
    return {field.field_id: field.content for field in package.fields if field.content}


def _predicate_k_number(content: str) -> str:
    match = re.search(r"K\d{6}", content.upper())
    return match.group(0) if match else content


def export_estar_xml(output: AgentOutput, package: SubmissionPackage | None = None) -> str:
    """Populate the FDA non-IVD eSTAR v7.0 XML template from a submission package."""
    package = package or output.submission_package
    if package is None:
        from fda_510k.output.submission_package import build_submission_package

        package = build_submission_package(output)

    xml = load_estar_xml_template()
    contents = _field_content_by_id(package)

    for field_id, tags in FIELD_TO_XML_TAGS.items():
        content = contents.get(field_id)
        if not content:
            continue

        if field_id == "user_predicate_mentions":
            k_number = _predicate_k_number(content)
            if len(tags) >= 1:
                xml = _inject_xml_text(xml, tags[0], k_number)
            if len(tags) >= 2:
                xml = _inject_xml_text(xml, tags[1], content)
            continue

        for tag in tags:
            xml = _inject_xml_text(xml, tag, content)

    if output.se_comparison and output.se_comparison.narrative_draft:
        narrative = output.se_comparison.narrative_draft
        for tag in SE_XML_TAGS:
            xml = _inject_xml_text(xml, tag, narrative)

    return xml


def resolve_estar_xml(output: AgentOutput, package: SubmissionPackage | None = None) -> str:
    """Return eSTAR XML, generating on demand for older packages missing ``estar_xml``."""
    package = package or output.submission_package
    if package is None:
        return ""

    existing = getattr(package, "estar_xml", None)
    if existing:
        return existing

    return export_estar_xml(output, package)


def attach_estar_xml(output: AgentOutput) -> AgentOutput:
    """Ensure ``output.submission_package`` includes populated ``estar_xml``."""
    package = output.submission_package
    if package is None:
        return output

    if getattr(package, "estar_xml", None):
        return output

    if "estar_xml" not in package.model_fields:
        return output

    updated = package.model_copy(
        update={
            "estar_xml": export_estar_xml(output, package),
            "estar_xml_version": ESTAR_XML_VERSION,
        }
    )
    return output.model_copy(update={"submission_package": updated})
