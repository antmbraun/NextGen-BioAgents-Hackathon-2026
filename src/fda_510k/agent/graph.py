from __future__ import annotations

from pathlib import Path
from typing import Literal

from langgraph.graph import END, StateGraph

from fda_510k.agent.state import AgentState
from fda_510k.extraction.profile_extractor import ProfileExtractor
from fda_510k.ingestion.pipeline import IngestionPipeline
from fda_510k.knowledge.db_510k import Device510kRepository
from fda_510k.models.output import AgentOutput, ClarifyingQuestion
from fda_510k.output.submission_package import build_submission_package
from fda_510k.tools.anticipated_fda_questions import generate_fda_questions
from fda_510k.tools.draft_all_estar_sections import draft_all_estar_sections
from fda_510k.tools.enrich_profile import enrich_profile
from fda_510k.tools.gap_analysis_estar import generate_clarifying_questions, run_gap_analysis
from fda_510k.tools.generate_se_table import generate_se_comparison
from fda_510k.tools.search_510k_db import search_predicates
from fda_510k.tools.validate_predicate import validate_predicate


def ingest_node(state: AgentState) -> AgentState:
    pipeline = IngestionPipeline()
    paths = [Path(p) for p in state.get("file_paths", [])]
    docs = pipeline.ingest_files(paths, user_text=state.get("user_text"))
    return {"parsed_docs": docs, "status_message": f"Ingested {len(docs)} document(s)"}


def extract_profile_node(state: AgentState) -> AgentState:
    extractor = ProfileExtractor()
    docs = state.get("parsed_docs", [])
    profile = extractor.extract(docs, clarifications=state.get("clarifications"))
    profile.input_manifest = IngestionPipeline.to_manifest(docs)
    return {"profile": profile, "status_message": "Extracted submission profile"}


def assess_gaps_node(state: AgentState) -> AgentState:
    profile = state["profile"]
    gaps = run_gap_analysis(profile)
    raw_questions = generate_clarifying_questions(profile, gaps)
    questions = [ClarifyingQuestion(**q) for q in raw_questions]
    return {
        "gaps": gaps,
        "clarifying_questions": questions,
        "status_message": f"Found {len(gaps)} checklist items",
    }


def need_clarification(state: AgentState) -> Literal["clarify", "analyze"]:
    clarifications = state.get("clarifications") or {}
    if clarifications:
        return "analyze"
    blockers = [g for g in state.get("gaps", []) if g.severity.value == "blocker" and g.status != "present"]
    if blockers and state.get("clarifying_questions"):
        return "clarify"
    return "analyze"


def clarify_node(state: AgentState) -> AgentState:
    return {"status_message": "Clarification questions prepared for user"}


def _predicate_search_context(state: AgentState) -> str:
    parts = [state.get("user_text", "").strip()]
    for doc in state.get("parsed_docs", []):
        if doc.raw_text:
            parts.append(doc.raw_text.strip())
    return "\n".join(part for part in parts if part)


def search_predicates_node(state: AgentState) -> AgentState:
    profile = state["profile"]
    repo = Device510kRepository()
    candidates = search_predicates(
        profile,
        repo=repo,
        search_context=_predicate_search_context(state),
    )

    # Validate user-mentioned predicates
    mentions = profile.user_predicate_mentions.value or []
    validated = []
    for mention in mentions:
        v = validate_predicate(str(mention), repo=repo)
        if v and v.k_number not in {c.k_number for c in candidates}:
            validated.append(v)

    all_candidates = validated + candidates
    return {
        "predicate_candidates": all_candidates[:5],
        "status_message": f"Ranked {len(all_candidates[:5])} predicate candidates",
    }


def enrich_profile_node(state: AgentState) -> AgentState:
    candidates = state.get("predicate_candidates", [])
    top_predicate = candidates[0] if candidates else None
    profile = enrich_profile(
        state["profile"],
        clarifications=state.get("clarifications"),
        top_predicate=top_predicate,
    )
    gaps = run_gap_analysis(profile)
    return {
        "profile": profile,
        "gaps": gaps,
        "status_message": "Enriched profile from clarifications and predicate",
    }


def generate_se_node(state: AgentState) -> AgentState:
    profile = state["profile"]
    candidates = state.get("predicate_candidates", [])
    if not candidates:
        return {"se_comparison": None, "status_message": "No predicate for SE comparison"}
    se = generate_se_comparison(profile, candidates[0])
    return {"se_comparison": se, "status_message": "Generated SE comparison draft"}


def draft_all_node(state: AgentState) -> AgentState:
    candidates = state.get("predicate_candidates", [])
    predicate = candidates[0] if candidates else None
    drafts = draft_all_estar_sections(
        state["profile"],
        state.get("gaps", []),
        predicate=predicate,
        se=state.get("se_comparison"),
    )
    return {"estar_drafts": drafts, "status_message": f"Drafted {len(drafts)} eSTAR sections"}


def anticipate_questions_node(state: AgentState) -> AgentState:
    questions = generate_fda_questions(
        state["profile"],
        state.get("gaps", []),
        state.get("se_comparison"),
    )
    return {"fda_questions": questions, "status_message": "Generated anticipated FDA questions"}


def format_output_node(state: AgentState) -> AgentState:
    output = AgentOutput(
        submission_profile=state["profile"],
        gap_analysis=state.get("gaps", []),
        predicate_candidates=state.get("predicate_candidates", []),
        se_comparison=state.get("se_comparison"),
        estar_drafts=state.get("estar_drafts", []),
        anticipated_fda_questions=state.get("fda_questions", []),
        clarifying_questions=state.get("clarifying_questions", []),
    )
    package = build_submission_package(output)
    output = output.model_copy(update={"submission_package": package})
    return {"output": output, "status_message": "Analysis complete"}


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("ingest", ingest_node)
    graph.add_node("extract_profile", extract_profile_node)
    graph.add_node("assess_gaps", assess_gaps_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("search_predicates", search_predicates_node)
    graph.add_node("enrich_profile", enrich_profile_node)
    graph.add_node("generate_se", generate_se_node)
    graph.add_node("draft_all", draft_all_node)
    graph.add_node("anticipate_questions", anticipate_questions_node)
    graph.add_node("format_output", format_output_node)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "extract_profile")
    graph.add_edge("extract_profile", "assess_gaps")
    graph.add_conditional_edges("assess_gaps", need_clarification, {"clarify": "clarify", "analyze": "search_predicates"})
    graph.add_edge("clarify", "search_predicates")
    graph.add_edge("search_predicates", "enrich_profile")
    graph.add_edge("enrich_profile", "generate_se")
    graph.add_edge("generate_se", "draft_all")
    graph.add_edge("draft_all", "anticipate_questions")
    graph.add_edge("anticipate_questions", "format_output")
    graph.add_edge("format_output", END)

    return graph.compile()


def run_agent(
    *,
    user_text: str = "",
    file_paths: list[Path | str] | None = None,
    clarifications: dict[str, str] | None = None,
) -> AgentOutput:
    app = build_graph()
    result = app.invoke(
        {
            "user_text": user_text,
            "file_paths": [str(p) for p in (file_paths or [])],
            "clarifications": clarifications or {},
            "errors": [],
        }
    )
    return result["output"]
