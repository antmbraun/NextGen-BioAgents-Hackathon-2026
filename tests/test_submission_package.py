from fda_510k.agent.graph import run_agent
from fda_510k.config import settings
from fda_510k.models.common import ExtractedField, FieldProvenance
from fda_510k.models.output import AgentOutput, EstarDraft
from fda_510k.models.profile import SubmissionProfile
from fda_510k.output.estar_mapping import build_complete_estar_mapping
from fda_510k.output.submission_package import build_submission_package
from fda_510k.tools.draft_all_estar_sections import draft_all_estar_sections
from fda_510k.tools.gap_analysis_estar import run_gap_analysis

import pytest

pytestmark = pytest.mark.skipif(
    not settings.fda_510k_db_path.exists(),
    reason="510(k) database not imported",
)


def test_draft_all_sections_produces_content():
    profile = SubmissionProfile(
        device_trade_name=ExtractedField.from_value(
            "TestPulse", confidence=0.8, provenance=FieldProvenance.EXPLICIT
        ),
        indications_for_use=ExtractedField.from_value(
            "Measure SpO2", confidence=0.8, provenance=FieldProvenance.EXPLICIT
        ),
    )
    gaps = run_gap_analysis(profile)
    drafts = draft_all_estar_sections(profile, gaps)
    assert len(drafts) > 0
    for d in drafts:
        assert d.content
        assert "DRAFT" in d.content or "Source:" in d.content


def test_submission_package_includes_estar_xml():
    profile = SubmissionProfile(
        device_trade_name=ExtractedField.from_value(
            "GlucoTrack", confidence=0.7, provenance=FieldProvenance.INFERRED
        ),
        indications_for_use=ExtractedField.from_value(
            "Continuous glucose monitoring", confidence=0.7, provenance=FieldProvenance.INFERRED
        ),
    )
    gaps = run_gap_analysis(profile)
    drafts = draft_all_estar_sections(profile, gaps)
    output = AgentOutput(submission_profile=profile, gap_analysis=gaps, estar_drafts=drafts)
    package = build_submission_package(output)
    assert package.estar_xml
    assert "<TradeName" in package.estar_xml
    assert "GlucoTrack" in package.estar_xml
    assert package.estar_xml_version == "nIVD_v7.0"


def test_submission_package_readiness():
    profile = SubmissionProfile(
        device_trade_name=ExtractedField.from_value(
            "GlucoTrack", confidence=0.7, provenance=FieldProvenance.INFERRED
        ),
    )
    gaps = run_gap_analysis(profile)
    drafts = draft_all_estar_sections(profile, gaps)
    output = AgentOutput(submission_profile=profile, gap_analysis=gaps, estar_drafts=drafts)
    package = build_submission_package(output)
    assert package.readiness_score >= 0.8
    assert len(package.fields) > 0
    for field in package.fields:
        assert field.content
        assert field.content != ""


def test_complete_estar_mapping_no_nulls():
    profile = SubmissionProfile(
        device_common_name=ExtractedField.from_value(
            "Glucose monitor", confidence=0.6, provenance=FieldProvenance.INFERRED
        ),
    )
    gaps = run_gap_analysis(profile)
    drafts = draft_all_estar_sections(profile, gaps)
    output = AgentOutput(submission_profile=profile, gap_analysis=gaps, estar_drafts=drafts)
    package = build_submission_package(output)
    mapping = build_complete_estar_mapping(output, package)
    for section in mapping["sections"].values():
        for field_data in section["fields"].values():
            assert field_data["value"] is not None
            assert field_data["content"] is not None


def test_minimal_input_agent_has_package():
    output = run_agent(user_text="Bluetooth glucose monitor for adults with diabetes, arm-worn sensor with mobile app.")
    assert output.submission_package is not None
    assert output.submission_package.readiness_score >= 0.5
