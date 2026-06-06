from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_KNOWLEDGE_DIR = Path(__file__).resolve().parent
_PROJECT_SRC = _KNOWLEDGE_DIR.parents[1]

ESTAR_TRANSCRIPT_PATH = _KNOWLEDGE_DIR / "estar_transcript_non_ivd_v3.md"
ESTAR_XML_TEMPLATE_PATH = _PROJECT_SRC / "nIVD_eSTAR_7-0_data.xml"

FIELD_TRANSCRIPT_SECTIONS: dict[str, str] = {
    "applicant_name": "Applicant Information",
    "contact": "Applicant Information",
    "submission_type": "Cover Letter / Letters of Reference",
    "product_code": "Classification",
    "device_trade_name": "Device Description",
    "device_common_name": "Device Description",
    "principle_of_operation": "Device Description",
    "materials": "Device Description",
    "components_accessories": "Device Description",
    "model_numbers": "Device Description",
    "indications_for_use": "Predicates and Substantial Equivalence",
    "user_predicate_mentions": "Predicates and Substantial Equivalence",
    "intended_use_population": "Predicates and Substantial Equivalence",
    "contraindications": "Labeling",
    "risk_analysis": "Software/Firmware & Cybersecurity/Interoperability",
    "design_controls": "Performance Testing",
    "bench_testing": "Performance Testing",
    "biocompatibility": "Biocompatibility",
    "emc": "EMC, Wireless, Electrical, Mechanical, and Thermal Safety",
    "software_vv": "Software/Firmware & Cybersecurity/Interoperability",
    "clinical_data": "Performance Testing",
    "cybersecurity_features": "Software/Firmware & Cybersecurity/Interoperability",
    "ifu_draft": "Labeling",
    "labeling_draft": "Labeling",
    "consensus_standards_cited": "Standards",
    "sterilization": "Reprocessing, Sterility, and Shelf-Life",
    "shelf_life": "Reprocessing, Sterility, and Shelf-Life",
}

CHECKLIST_SECTION_TRANSCRIPT: dict[str, str] = {
    "Administrative Information": "Applicant Information",
    "Device Description": "Device Description",
    "Predicates and Substantial Equivalence": "Predicates and Substantial Equivalence",
    "Risk Management and Design Controls": "Performance Testing",
    "Design Verification and Validation": "Performance Testing",
    "Software and Cybersecurity": "Software/Firmware & Cybersecurity/Interoperability",
    "Labeling": "Labeling",
    "Additional Information": "Standards",
}


def load_estar_transcript() -> str:
    return ESTAR_TRANSCRIPT_PATH.read_text(encoding="utf-8")


def load_estar_xml_template() -> str:
    return ESTAR_XML_TEMPLATE_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _parsed_sections() -> dict[str, str]:
    text = load_estar_transcript()
    if text.startswith("---"):
        parts = text.split("---", 2)
        text = parts[2] if len(parts) > 2 else text

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n...[eSTAR transcript truncated]"


def get_estar_guidance(
    *,
    field_id: str | None = None,
    section_label: str | None = None,
    max_chars: int = 3500,
) -> str:
    """Return eSTAR filing instructions for a checklist field or section."""
    transcript_key = None
    if field_id:
        transcript_key = FIELD_TRANSCRIPT_SECTIONS.get(field_id)
    if not transcript_key and section_label:
        transcript_key = CHECKLIST_SECTION_TRANSCRIPT.get(section_label)

    if not transcript_key:
        return ""

    content = _parsed_sections().get(transcript_key, "")
    if not content:
        return ""

    header = f"eSTAR instructions ({transcript_key}):\n"
    return _truncate(header + content, max_chars)
