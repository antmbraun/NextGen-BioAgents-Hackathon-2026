"""Streamlit web UI for the FDA 510(k) Submission Assistant."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _inject_streamlit_secrets() -> None:
    """Map Streamlit Cloud secrets into env vars for pydantic settings."""
    for name in ("NEBIUS_API_KEY", "NEBIUS_MODEL", "NEBIUS_BASE_URL"):
        if os.environ.get(name):
            continue
        try:
            value = st.secrets[name]
            if value:
                os.environ[name] = str(value)
        except (KeyError, FileNotFoundError, AttributeError):
            pass


_inject_streamlit_secrets()

from fda_510k.agent.graph import run_agent  # noqa: E402
from fda_510k.config import get_nebius_model, reload_settings, settings  # noqa: E402

reload_settings()
from fda_510k.llm.nebius_client import NebiusClient  # noqa: E402
from fda_510k.output.estar_mapping import build_complete_estar_mapping  # noqa: E402
from fda_510k.output.estar_xml_export import attach_estar_xml, resolve_estar_xml  # noqa: E402
from fda_510k.output.formatter import (  # noqa: E402
    format_html_report,
    format_submission_draft_html,
    save_output_json,
)

DISCLAIMER = (
    "**DRAFT — REQUIRES REGULATORY REVIEW**  \n"
    "This tool is a drafting assistant only. It does not provide legal or regulatory advice.  \n"
    "All outputs require human regulatory review before FDA submission."
)

MIN_INPUT_CHARS = 30


@st.cache_data
def _load_ui_copy() -> dict:
    path = settings.data_dir / "ui_copy.yaml"
    if path.exists():
        with path.open() as f:
            return yaml.safe_load(f)
    return {}


def _system_status() -> dict:
    llm = NebiusClient()
    return {
        "llm": llm.is_available(),
        "db": settings.fda_510k_db_path.exists(),
        "model": get_nebius_model(),
    }


def _render_sidebar() -> None:
    copy = _load_ui_copy().get("sidebar", {})
    status = _system_status()

    st.sidebar.title(copy.get("title", "🥪 PBJ - Predicates, Building & Journey"))
    st.sidebar.markdown(copy.get("about", "FDA 510(k) drafting assistant."))

    st.sidebar.subheader("How to use")
    for i, step in enumerate(copy.get("steps", []), 1):
        st.sidebar.markdown(f"{i}. {step}")

    with st.sidebar.expander("What you can upload"):
        for item in copy.get("upload_types", []):
            st.sidebar.markdown(f"- {item}")

    with st.sidebar.expander("What you get"):
        for item in copy.get("outputs", []):
            st.sidebar.markdown(f"- {item}")

    with st.sidebar.expander("Tips for minimal input"):
        st.sidebar.markdown(copy.get("minimal_input_tip", "Even one paragraph works."))

    with st.sidebar.expander("System status"):
        st.sidebar.markdown(
            f"**LLM (Nebius):** {'Ready' if status['llm'] else 'Offline — template drafting used'}"
        )
        st.sidebar.markdown(f"**510(k) database:** {'Loaded' if status['db'] else 'Missing — run import script'}")
        st.sidebar.markdown(f"**Model:** {status['model']}")
        if not status["db"]:
            st.sidebar.code("python scripts/import_510k_db.py", language="bash")
        if not status["llm"]:
            st.sidebar.caption(
                "Set NEBIUS_API_KEY from [Nebius Token Factory](https://tokenfactory.nebius.com/)"
            )

    st.sidebar.divider()
    st.sidebar.caption(copy.get("disclaimer_short", "Drafting assistant only. Not legal advice."))


def _render_readiness_banner(output) -> None:
    pkg = output.submission_package
    if not pkg:
        return
    pct = int(pkg.readiness_score * 100)
    st.success(
        f"**Submission draft: {len(pkg.fields)} fields — {pct}% ready** "
        f"({pkg.explicit_count} explicit, {pkg.inferred_count} inferred, {pkg.drafted_count} drafted). "
        "Review items marked VERIFY before filing."
    )
    st.progress(pkg.readiness_score)


def _render_submission_package(output) -> None:
    output = attach_estar_xml(output)
    st.session_state.output = output
    pkg = output.submission_package
    if not pkg:
        st.warning("Submission package not generated.")
        return

    _render_readiness_banner(output)
    estar_xml = resolve_estar_xml(output, pkg)

    col1, col2, col3 = st.columns(3)
    html_draft = format_submission_draft_html(pkg)
    json_mapping = json.dumps(build_complete_estar_mapping(output, pkg), indent=2)

    with col1:
        st.download_button(
            "Download Submission Draft (HTML)",
            html_draft,
            file_name="510k_submission_draft.html",
            mime="text/html",
            use_container_width=True,
            type="primary",
        )
    with col2:
        st.download_button(
            "Download eSTAR Data (XML)",
            estar_xml,
            file_name="nIVD_eSTAR_7-0_data.xml",
            mime="application/xml",
            use_container_width=True,
            disabled=not estar_xml,
        )
    with col3:
        st.download_button(
            "Download Complete eSTAR Mapping (JSON)",
            json_mapping,
            file_name="estar_mapping_complete.json",
            mime="application/json",
            use_container_width=True,
        )

    with st.expander("Review checklist — items needing human verification", expanded=True):
        for item in pkg.review_items[:20]:
            st.markdown(f"- {item}")
        if len(pkg.review_items) > 20:
            st.caption(f"... and {len(pkg.review_items) - 20} more")

    sections: dict[str, dict] = {}
    for field in pkg.fields:
        sec = sections.setdefault(field.section_id, {"label": field.section_label, "fields": []})
        sec["fields"].append(field)

    for section_id, section in sections.items():
        with st.expander(f"{section['label']}", expanded=False):
            for field in section["fields"]:
                badge = {"explicit": "🟢", "inferred": "🟡", "drafted": "🟣"}.get(field.provenance, "⚪")
                verify = " **[VERIFY]**" if field.requires_review else ""
                st.markdown(f"{badge} **{field.label}** (`{field.provenance}`){verify}")
                st.text_area(
                    field.field_id,
                    value=field.content,
                    height=120,
                    disabled=True,
                    label_visibility="collapsed",
                )


def _render_profile_summary(output) -> None:
    profile = output.submission_profile
    summary = profile.extraction_summary
    c1, c2, c3 = st.columns(3)
    c1.metric("Explicit fields", summary.explicit_count)
    c2.metric("Inferred fields", summary.inferred_count)
    c3.metric("Missing fields", summary.missing_count)

    with st.expander("Extracted profile fields"):
        for name, field in profile.iter_fields():
            if field.value is not None:
                st.markdown(
                    f"**{name}** `[{field.provenance.value}]` "
                    f"(conf: {field.confidence:.2f}): {field.value}"
                )


def _render_gaps(output) -> None:
    blockers = [g for g in output.gap_analysis if g.severity.value == "blocker" and g.status != "present"]
    if blockers:
        st.error(f"{len(blockers)} blocker gap(s) — address in submission draft before filing")
    for gap in output.gap_analysis:
        icon = {"missing": "🔴", "weak": "🟡", "present": "🟢"}.get(gap.status, "⚪")
        st.markdown(
            f"{icon} **{gap.label}** — `{gap.severity.value}` / `{gap.status}` "
            f"_(section: {gap.estar_section_id})_"
        )


def _render_predicates(output) -> None:
    if not output.predicate_candidates:
        st.info("No predicate candidates found. Provide more device details or import the 510(k) database.")
        return
    for i, pred in enumerate(output.predicate_candidates, 1):
        with st.expander(f"#{i} {pred.k_number} — {pred.device_name} (score: {pred.rank_score})"):
            fda_url = f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={pred.k_number}"
            st.markdown(f"[View on FDA 510(k) Database ↗]({fda_url})")
            st.write(f"**Applicant:** {pred.applicant}")
            st.write(f"**Product code:** {pred.product_code}")
            st.write(f"**Clearance date:** {pred.decision_date}")
            st.write(f"**Rationale:** {pred.rank_rationale}")
            if pred.risks:
                st.warning("Risks: " + "; ".join(pred.risks))


def _render_se(output) -> None:
    se = output.se_comparison
    if not se:
        st.info("No SE comparison generated — predicate required.")
        return
    st.subheader(f"Predicate: {se.predicate_device_name} ({se.predicate_k_number})")
    rows = [
        {
            "Characteristic": r.characteristic,
            "Subject": r.subject_device,
            "Predicate": r.predicate_device,
            "Notes": r.comparison_notes,
        }
        for r in se.rows
    ]
    st.dataframe(rows, use_container_width=True)
    st.markdown(se.narrative_draft)
    for note in se.confidence_notes:
        st.caption(f"⚠ {note}")


def main() -> None:
    st.set_page_config(
        page_title="PBJ - Predicates, Building & Journey",
        page_icon="🥪",
        layout="wide",
    )
    _render_sidebar()

    st.title("🥪 PBJ - Predicates, Building & Journey")
    ui_main = _load_ui_copy().get("main", {})
    st.subheader(ui_main.get("subheading", "A delicious FDA 510k submission assistant"))
    st.caption("Upload anything — notes, specs, slide decks, test reports, or a single paragraph.")

    st.info(DISCLAIMER)

    if "output" not in st.session_state:
        st.session_state.output = None
    if "clarifications" not in st.session_state:
        st.session_state.clarifications = {}
    if "pending_reanalyze" not in st.session_state:
        st.session_state.pending_reanalyze = False
    if "saved_user_text" not in st.session_state:
        st.session_state.saved_user_text = ""
    if "saved_file_bytes" not in st.session_state:
        st.session_state.saved_file_bytes = []

    user_text = st.text_area(
        "Describe your device (free text)",
        placeholder="We're building a Bluetooth-enabled continuous glucose monitor for adults with diabetes...",
        height=150,
    )
    if user_text.strip() and len(user_text.strip()) < MIN_INPUT_CHARS:
        st.caption(ui_main.get("short_input_hint", "Short input OK — we'll infer and mark for review."))

    uploaded_files = st.file_uploader(
        "Upload documents (optional)",
        accept_multiple_files=True,
        type=["pdf", "docx", "pptx", "xlsx", "txt", "md", "json", "zip", "csv"],
    )

    analyze_clicked = st.button("Analyze", type="primary", use_container_width=True)
    should_run = analyze_clicked or st.session_state.pending_reanalyze

    if should_run:
        run_text = user_text.strip() or st.session_state.saved_user_text
        run_files = list(uploaded_files or [])
        if analyze_clicked and (user_text.strip() or uploaded_files):
            st.session_state.saved_user_text = user_text.strip()
            st.session_state.saved_file_bytes = [
                {"name": uf.name, "data": uf.getvalue()} for uf in (uploaded_files or [])
            ]

        min_chars = ui_main.get("min_chars", MIN_INPUT_CHARS)
        has_files = bool(run_files or st.session_state.saved_file_bytes)
        if len(run_text) < min_chars and not has_files:
            st.error(f"Please enter at least {min_chars} characters or upload a file.")
            st.session_state.pending_reanalyze = False
        else:
            file_paths: list[Path] = []
            with tempfile.TemporaryDirectory() as tmpdir:
                files_to_process = run_files
                if not files_to_process and st.session_state.saved_file_bytes:
                    files_to_process = st.session_state.saved_file_bytes
                for uf in files_to_process:
                    name = uf.name if hasattr(uf, "name") else uf["name"]
                    data = uf.getvalue() if hasattr(uf, "getvalue") else uf["data"]
                    dest = Path(tmpdir) / name
                    dest.write_bytes(data)
                    file_paths.append(dest)

                with st.status("Running analysis...", expanded=True) as status:
                    try:
                        output = run_agent(
                            user_text=run_text,
                            file_paths=file_paths,
                            clarifications=st.session_state.clarifications,
                        )
                        st.session_state.output = attach_estar_xml(output)
                        st.session_state.pending_reanalyze = False
                        save_output_json(output)
                        status.update(label="Analysis complete", state="complete")
                    except FileNotFoundError as exc:
                        st.session_state.pending_reanalyze = False
                        status.update(label="Database missing", state="error")
                        st.error(str(exc))
                    except Exception as exc:
                        st.session_state.pending_reanalyze = False
                        status.update(label="Error", state="error")
                        st.error(f"Analysis failed: {exc}")

    output = st.session_state.output
    if output and output.clarifying_questions and not st.session_state.clarifications:
        st.subheader("Clarifying questions (optional — improves accuracy)")
        clarifications: dict[str, str] = {}
        for q in output.clarifying_questions:
            answer = st.text_input(q.question, key=f"clarify_{q.field_id}")
            if answer:
                clarifications[q.field_id] = answer
        if st.button("Re-analyze with answers", disabled=not clarifications):
            st.session_state.clarifications = clarifications
            st.session_state.pending_reanalyze = True
            st.rerun()

    if output:
        tab_pkg, tab_profile, tab_gaps, tab_pred, tab_se, tab_drafts, tab_fda, tab_export = st.tabs(
            [
                "Submission Package",
                "Profile",
                "Gaps",
                "Predicates",
                "SE Comparison",
                "Section Drafts",
                "FDA Questions",
                "Export",
            ]
        )

        with tab_pkg:
            _render_submission_package(output)

        with tab_profile:
            _render_profile_summary(output)

        with tab_gaps:
            _render_gaps(output)

        with tab_pred:
            _render_predicates(output)

        with tab_se:
            _render_se(output)

        with tab_drafts:
            if not output.estar_drafts:
                st.info("No section drafts generated.")
            for draft in output.estar_drafts:
                st.subheader(f"{draft.section_label} — {draft.field_id}")
                st.markdown(draft.content)

        with tab_fda:
            for q in output.anticipated_fda_questions:
                risk_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(q.risk_level, "⚪")
                st.markdown(f"{risk_color} **{q.category}** ({q.risk_level})")
                st.write(q.question)
                st.caption(f"Mitigation: {q.mitigation}")

        with tab_export:
            json_str = output.model_dump_json(indent=2)
            st.download_button("Download Full Analysis JSON", json_str, file_name="510k_analysis.json", mime="application/json")
            html = format_html_report(output)
            st.download_button("Download Analysis Report (HTML)", html, file_name="510k_report.html", mime="text/html")
            if output.submission_package:
                st.download_button(
                    "Download Submission Draft (HTML)",
                    format_submission_draft_html(output.submission_package),
                    file_name="510k_submission_draft.html",
                    mime="text/html",
                )
                st.download_button(
                    "Download Complete eSTAR Mapping (JSON)",
                    json.dumps(build_complete_estar_mapping(output), indent=2),
                    file_name="estar_mapping_complete.json",
                    mime="application/json",
                )
                estar_xml = resolve_estar_xml(output, output.submission_package)
                if estar_xml:
                    st.download_button(
                        "Download eSTAR Data (XML)",
                        estar_xml,
                        file_name="nIVD_eSTAR_7-0_data.xml",
                        mime="application/xml",
                    )

    st.divider()
    st.caption("Drafting assistant only. Not legal or regulatory advice. Human review required before FDA submission.")


if __name__ == "__main__":
    main()
