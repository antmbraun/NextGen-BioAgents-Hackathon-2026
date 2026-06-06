from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Template

from fda_510k.config import settings
from fda_510k.models.output import AgentOutput, SubmissionPackage

HTML_TEMPLATE = Template("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>510(k) Draft Report — {{ profile_id }}</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
    .disclaimer { background: #fff3cd; border: 1px solid #ffc107; padding: 1rem; border-radius: 6px; margin-bottom: 2rem; }
    h1, h2, h3 { color: #0d3b66; }
    table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
    th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: left; vertical-align: top; }
    th { background: #f0f4f8; }
    .blocker { color: #b00020; font-weight: bold; }
    .recommended { color: #e65100; }
    .draft { background: #f5f5f5; padding: 1rem; border-left: 4px solid #888; white-space: pre-wrap; }
    .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.85rem; }
    .badge-explicit { background: #c8e6c9; }
    .badge-inferred { background: #fff9c4; }
    .badge-missing { background: #ffcdd2; }
  </style>
</head>
<body>
  <div class="disclaimer">
    <strong>DRAFT — REQUIRES REGULATORY REVIEW</strong>
    <ul>
    {% for d in disclaimers %}
      <li>{{ d }}</li>
    {% endfor %}
    </ul>
  </div>

  <h1>510(k) Submission Assistant Report</h1>
  <p>Profile ID: {{ profile_id }} | Generated: {{ created_at }}</p>

  <h2>Extraction Summary</h2>
  <p>Explicit: {{ summary.explicit_count }} | Inferred: {{ summary.inferred_count }} | Missing: {{ summary.missing_count }}</p>

  <h2>Gap Analysis</h2>
  <table>
    <tr><th>Section</th><th>Field</th><th>Severity</th><th>Status</th></tr>
    {% for g in gaps %}
    <tr>
      <td>{{ g.estar_section_id }}</td>
      <td>{{ g.label }}</td>
      <td class="{{ g.severity.value }}">{{ g.severity.value }}</td>
      <td>{{ g.status }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Predicate Candidates</h2>
  {% if predicates %}
  <table>
    <tr><th>Rank</th><th>K#</th><th>Device</th><th>Applicant</th><th>Score</th><th>Rationale</th></tr>
    {% for p in predicates %}
    <tr>
      <td>{{ loop.index }}</td>
      <td>{{ p.k_number }}</td>
      <td>{{ p.device_name }}</td>
      <td>{{ p.applicant }}</td>
      <td>{{ p.rank_score }}</td>
      <td>{{ p.rank_rationale }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p>No predicate candidates found. Import 510(k) database or provide more device details.</p>
  {% endif %}

  {% if se_comparison %}
  <h2>Substantial Equivalence Comparison</h2>
  <p>Predicate: {{ se_comparison.predicate_device_name }} ({{ se_comparison.predicate_k_number }})</p>
  <table>
    <tr><th>Characteristic</th><th>Subject</th><th>Predicate</th><th>Notes</th></tr>
    {% for row in se_comparison.rows %}
    <tr>
      <td>{{ row.characteristic }}</td>
      <td>{{ row.subject_device }}</td>
      <td>{{ row.predicate_device }}</td>
      <td>{{ row.comparison_notes }}</td>
    </tr>
    {% endfor %}
  </table>
  <div class="draft">{{ se_comparison.narrative_draft }}</div>
  {% endif %}

  <h2>Section Drafts (Gaps Only)</h2>
  {% for draft in estar_drafts %}
  <h3>{{ draft.section_label }} — {{ draft.field_id }}</h3>
  <div class="draft">{{ draft.content }}</div>
  {% endfor %}

  <h2>Anticipated FDA Questions</h2>
  {% for q in fda_questions %}
  <h3>{{ q.category }} ({{ q.risk_level }})</h3>
  <p>{{ q.question }}</p>
  <p><strong>Mitigation:</strong> {{ q.mitigation }}</p>
  {% endfor %}

  {% if clarifying_questions %}
  <h2>Clarifying Questions for User</h2>
  <ol>
  {% for q in clarifying_questions %}
    <li>{{ q.question }}</li>
  {% endfor %}
  </ol>
  {% endif %}
</body>
</html>
""")


def format_html_report(output: AgentOutput) -> str:
    profile = output.submission_profile
    return HTML_TEMPLATE.render(
        profile_id=profile.profile_id,
        created_at=profile.created_at.isoformat(),
        summary=profile.extraction_summary,
        disclaimers=output.disclaimers,
        gaps=output.gap_analysis,
        predicates=output.predicate_candidates,
        se_comparison=output.se_comparison,
        estar_drafts=output.estar_drafts,
        fda_questions=output.anticipated_fda_questions,
        clarifying_questions=output.clarifying_questions,
    )


SUBMISSION_DRAFT_TEMPLATE = Template("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>510(k) Submission Draft — {{ version }}</title>
  <style>
    body { font-family: Georgia, serif; max-width: 900px; margin: 2rem auto; padding: 0 1.5rem; line-height: 1.6; }
    .disclaimer { background: #fff3cd; border: 2px solid #ffc107; padding: 1rem; margin-bottom: 2rem; }
    h1 { color: #0d3b66; border-bottom: 2px solid #0d3b66; padding-bottom: 0.5rem; }
    h2 { color: #1a5276; margin-top: 2rem; }
    h3 { color: #333; }
    .field { margin-bottom: 1.5rem; page-break-inside: avoid; }
    .badge { font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 3px; margin-left: 0.5rem; }
    .badge-explicit { background: #c8e6c9; }
    .badge-inferred { background: #fff9c4; }
    .badge-drafted { background: #e1bee7; }
    .content { background: #fafafa; padding: 1rem; border-left: 4px solid #0d3b66; white-space: pre-wrap; }
    .verify { color: #b00020; font-weight: bold; font-size: 0.85rem; }
    .meta { color: #666; font-size: 0.9rem; }
  </style>
</head>
<body>
  <div class="disclaimer">
    <strong>DRAFT — REQUIRES REGULATORY REVIEW</strong>
    <p>This document is a drafting assistant output. Do not submit to FDA without expert regulatory review.
    Fields marked VERIFY or with inferred/drafted badges require human verification.</p>
    <p>Readiness: {{ readiness_pct }}% | Explicit: {{ explicit_count }} | Inferred: {{ inferred_count }} | Drafted: {{ drafted_count }}</p>
  </div>

  <h1>510(k) Submission Draft Package</h1>
  <p class="meta">eSTAR version: {{ version }} | Generated for regulatory review</p>

  {% for section_id, section in sections.items() %}
  <h2>{{ section.label }}</h2>
  {% for field in section.fields %}
  <div class="field">
    <h3>{{ field.label }}
      <span class="badge badge-{{ field.provenance }}">{{ field.provenance }}</span>
      {% if field.requires_review %}<span class="verify">[VERIFY]</span>{% endif %}
    </h3>
    <div class="content">{{ field.content }}</div>
  </div>
  {% endfor %}
  {% endfor %}

  {% if review_items %}
  <h2>Review Checklist</h2>
  <ul>
  {% for item in review_items %}
    <li>{{ item }}</li>
  {% endfor %}
  </ul>
  {% endif %}
</body>
</html>
""")


def format_submission_draft_html(package: SubmissionPackage) -> str:
    sections: dict = {}
    for field in package.fields:
        sec = sections.setdefault(
            field.section_id,
            {"label": field.section_label, "fields": []},
        )
        sec["fields"].append(field)

    return SUBMISSION_DRAFT_TEMPLATE.render(
        version=package.version,
        readiness_pct=int(package.readiness_score * 100),
        explicit_count=package.explicit_count,
        inferred_count=package.inferred_count,
        drafted_count=package.drafted_count,
        sections=sections,
        review_items=package.review_items,
    )


def save_output_json(output: AgentOutput, path: Path | None = None) -> Path:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = path or settings.output_dir / f"{output.submission_profile.profile_id}.json"
    out_path.write_text(output.model_dump_json(indent=2))
    if output.submission_package and output.submission_package.estar_xml:
        xml_path = out_path.with_suffix(".estar.xml")
        xml_path.write_text(output.submission_package.estar_xml, encoding="utf-8")
    return out_path
