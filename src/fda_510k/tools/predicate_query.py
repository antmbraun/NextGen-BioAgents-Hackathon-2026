from __future__ import annotations

import re

from fda_510k.models.common import FieldProvenance
from fda_510k.models.profile import SubmissionProfile

DEVICE_PHRASES: list[tuple[str, str]] = [
    ("continuous glucose monitor", "continuous glucose monitor"),
    ("glucose monitor", "glucose monitor"),
    ("blood glucose", "glucose monitor"),
    ("cgm", "continuous glucose monitor"),
    ("surgical stapler", "surgical stapler"),
    ("stapler", "surgical stapler"),
    ("defibrillator", "defibrillator"),
    ("aed", "automated external defibrillator"),
    ("blood pressure", "blood pressure monitor"),
    ("sphygmomanometer", "blood pressure monitor"),
    ("pulse oximeter", "pulse oximeter"),
    ("oximeter", "pulse oximeter"),
    ("infusion pump", "infusion pump"),
    ("ventilator", "ventilator"),
    ("catheter", "catheter"),
    ("stent", "vascular stent"),
    ("pacemaker", "pacemaker"),
    ("ultrasound", "ultrasound system"),
    ("mri", "magnetic resonance imaging"),
    ("x-ray", "x-ray system"),
    ("dental implant", "dental implant"),
    ("hip replacement", "hip prosthesis"),
    ("knee replacement", "knee prosthesis"),
    ("wound dressing", "wound dressing"),
    ("insulin pump", "insulin pump"),
]

STOP_WORDS = {
    "about",
    "after",
    "also",
    "been",
    "being",
    "device",
    "for",
    "from",
    "have",
    "including",
    "into",
    "medical",
    "patient",
    "patients",
    "that",
    "the",
    "this",
    "used",
    "using",
    "with",
    "without",
}


def _phrase_query(text: str) -> str | None:
    lowered = text.lower()
    for phrase, query in DEVICE_PHRASES:
        if phrase in lowered:
            return query
    return None


def _keyword_query(text: str, *, max_terms: int = 6) -> str:
    phrase = _phrase_query(text)
    if phrase:
        return phrase

    words = re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
    keywords = [word for word in words if word not in STOP_WORDS]
    if keywords:
        return " ".join(keywords[:max_terms])
    return ""


def trusted_product_code(profile: SubmissionProfile) -> str | None:
    field = profile.product_code
    if field.value is None:
        return None
    if field.provenance == FieldProvenance.EXPLICIT:
        return str(field.value).upper()
    if field.provenance == FieldProvenance.INFERRED and field.confidence >= 0.75:
        return str(field.value).upper()
    return None


def build_predicate_search_query(
    profile: SubmissionProfile,
    *,
    search_context: str = "",
) -> tuple[str, str | None, str | None]:
    """Build FTS query and optional FDA code filters from profile + raw input."""
    query_parts: list[str] = []

    for field in (
        profile.device_trade_name,
        profile.device_common_name,
        profile.indications_for_use,
        profile.principle_of_operation,
    ):
        if field.value:
            query_parts.append(str(field.value))

    if profile.competitive_devices.value:
        query_parts.extend(str(item) for item in profile.competitive_devices.value)

    if query_parts:
        query_text = " ".join(query_parts)
    else:
        query_text = _keyword_query(search_context)

    product_code = trusted_product_code(profile)
    regulation_number = (
        str(profile.regulation_number.value)
        if profile.regulation_number.value
        and profile.regulation_number.provenance != FieldProvenance.MISSING
        else None
    )

    return query_text, product_code, regulation_number
