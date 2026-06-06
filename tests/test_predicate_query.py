from fda_510k.config import settings
from fda_510k.models.common import ExtractedField, FieldProvenance
from fda_510k.models.profile import SubmissionProfile
from fda_510k.tools.predicate_query import build_predicate_search_query
from fda_510k.tools.search_510k_db import search_predicates

import pytest

pytestmark = pytest.mark.skipif(
    not settings.fda_510k_db_path.exists(),
    reason="510(k) database not imported",
)


def test_build_predicate_search_query_from_context():
    profile = SubmissionProfile()
    query, product_code, _ = build_predicate_search_query(
        profile,
        search_context="Surgical stapler for laparoscopic tissue closure.",
    )
    assert "surgical stapler" in query.lower()
    assert product_code is None


def test_different_inputs_return_different_predicates():
    inputs = [
        "Bluetooth glucose monitor for adults with diabetes.",
        "Surgical stapler for internal tissue closure.",
        "Automated external defibrillator for emergency cardiac resuscitation.",
    ]
    results = []
    for text in inputs:
        profile = SubmissionProfile()
        candidates = search_predicates(profile, search_context=text, top_k=3)
        results.append({c.k_number for c in candidates})

    assert results[0] != results[1]
    assert results[1] != results[2]


def test_low_confidence_product_code_not_used_as_filter():
    profile = SubmissionProfile(
        product_code=ExtractedField.from_value(
            "MYN",
            confidence=0.45,
            provenance=FieldProvenance.INFERRED,
        ),
    )
    _, product_code, _ = build_predicate_search_query(
        profile,
        search_context="glucose monitor for diabetes management",
    )
    assert product_code is None
