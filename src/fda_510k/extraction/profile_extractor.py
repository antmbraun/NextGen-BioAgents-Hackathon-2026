from __future__ import annotations

from typing import Any

from fda_510k.config import settings
from fda_510k.extraction.prompts.extraction_passes import (
    PASS_1_IDENTITY,
    PASS_2_TECHNOLOGY,
    PASS_3_TESTING,
    PASS_4_PREDICATES,
)
from fda_510k.ingestion.pipeline import ParsedDocument
from fda_510k.llm.gemini_client import GeminiClient
from fda_510k.models.common import ExtractedField, FieldProvenance, SourceRef
from fda_510k.models.profile import SubmissionProfile
from fda_510k.tools.predicate_query import _phrase_query


class ProfileExtractor:
    PASSES = [
        ("identity", PASS_1_IDENTITY),
        ("technology", PASS_2_TECHNOLOGY),
        ("testing", PASS_3_TESTING),
        ("predicates", PASS_4_PREDICATES),
    ]

    def __init__(self, llm: GeminiClient | None = None) -> None:
        self.llm = llm or GeminiClient()

    def _build_context(self, docs: list[ParsedDocument], max_chunks: int | None = None) -> str:
        max_chunks = max_chunks or settings.max_chunks_per_pass
        chunks = []
        for doc in docs:
            for chunk in doc.chunks[:max_chunks]:
                ref = chunk.source_ref
                header = f"[{ref.doc_name}"
                if ref.page:
                    header += f" p.{ref.page}"
                header += "]"
                chunks.append(f"{header}\n{chunk.text}")
        return "\n\n---\n\n".join(chunks[:max_chunks])

    def _field_from_raw(
        self,
        field_name: str,
        raw: dict[str, Any] | None,
        docs: list[ParsedDocument],
    ) -> ExtractedField:
        if not raw or raw.get("value") is None:
            return ExtractedField.missing()

        provenance = FieldProvenance(raw.get("provenance", "inferred"))
        confidence = float(raw.get("confidence", 0.5))
        if provenance == FieldProvenance.INFERRED:
            confidence = min(confidence, 0.6)
        elif provenance == FieldProvenance.EXPLICIT:
            confidence = max(confidence, 0.7)

        source_refs: list[SourceRef] = []
        snippet = raw.get("snippet")
        if snippet and docs:
            source_refs.append(
                SourceRef(
                    doc_id=docs[0].doc_id,
                    doc_name=docs[0].doc_name,
                    snippet=str(snippet)[:300],
                )
            )

        return ExtractedField(
            value=raw["value"],
            confidence=confidence,
            provenance=provenance,
            source_refs=source_refs,
            notes=raw.get("notes"),
        )

    def _run_pass(self, prompt: str, context: str) -> dict[str, Any]:
        full_prompt = f"SOURCE DOCUMENTS:\n{context}\n\nTASK:\n{prompt}"
        try:
            result = self.llm.generate_json(full_prompt, system="You are a regulatory document analyst.")
            if isinstance(result, dict):
                return result
        except (ValueError, Exception):
            pass
        return {}

    def extract(
        self,
        docs: list[ParsedDocument],
        *,
        use_llm: bool = True,
        clarifications: dict[str, str] | None = None,
    ) -> SubmissionProfile:
        profile = SubmissionProfile(input_manifest=[])
        context = self._build_context(docs)

        if clarifications:
            clar_text = "\n".join(f"{k}: {v}" for k, v in clarifications.items())
            context += f"\n\nUSER CLARIFICATIONS:\n{clar_text}"

        if use_llm and self.llm.is_available():
            for _, prompt in self.PASSES:
                raw_pass = self._run_pass(prompt, context)
                for field_name, raw_field in raw_pass.items():
                    if hasattr(profile, field_name):
                        setattr(
                            profile,
                            field_name,
                            self._field_from_raw(field_name, raw_field, docs),
                        )
            if self._needs_heuristic_backfill(profile):
                profile = self._merge_heuristic(profile, docs)
        else:
            profile = self._heuristic_extract(docs)

        profile.recompute_summary()
        return profile

    @staticmethod
    def _is_missing(field: ExtractedField | object) -> bool:
        return field.provenance == FieldProvenance.MISSING or field.value is None

    def _needs_heuristic_backfill(self, profile: SubmissionProfile) -> bool:
        return all(
            self._is_missing(getattr(profile, name))
            for name in (
                "device_trade_name",
                "device_common_name",
                "indications_for_use",
                "product_code",
            )
        )

    def _merge_heuristic(
        self,
        profile: SubmissionProfile,
        docs: list[ParsedDocument],
    ) -> SubmissionProfile:
        heuristic = self._heuristic_extract(docs)
        for field_name in SubmissionProfile.model_fields:
            if field_name in {"profile_id", "created_at", "input_manifest", "extraction_summary"}:
                continue
            current = getattr(profile, field_name)
            candidate = getattr(heuristic, field_name)
            if self._is_missing(current) and not self._is_missing(candidate):
                setattr(profile, field_name, candidate)
        return profile

    def _heuristic_extract(self, docs: list[ParsedDocument]) -> SubmissionProfile:
        """Fallback when Gemini is unavailable or returns sparse fields."""
        import re

        profile = SubmissionProfile()
        full_text = "\n".join(d.raw_text for d in docs)
        lowered = full_text.lower()
        primary_doc = docs[0] if docs else None
        source_ref = (
            [SourceRef(doc_id=primary_doc.doc_id, doc_name=primary_doc.doc_name, snippet=full_text[:200])]
            if primary_doc
            else []
        )

        def set_field(field: str, value: object, *, confidence: float = 0.5, notes: str) -> None:
            setattr(
                profile,
                field,
                ExtractedField.from_value(
                    value,
                    confidence=confidence,
                    provenance=FieldProvenance.INFERRED,
                    source_refs=source_ref,
                    notes=notes,
                ),
            )

        device_query = _phrase_query(full_text)
        if device_query:
            set_field(
                "device_common_name",
                device_query.title(),
                notes="Heuristic device-type extraction from input text",
            )

        first_sentence = re.split(r"[.\n]", full_text.strip(), maxsplit=1)[0].strip()
        if len(first_sentence) >= 20:
            set_field(
                "indications_for_use",
                first_sentence,
                confidence=0.45,
                notes="Heuristic extraction from opening sentence",
            )

        if any(kw in lowered for kw in ("software", "firmware", "app", "bluetooth", "mobile")):
            set_field("software_present", True, notes="Heuristic extraction from software keywords")
        if any(kw in lowered for kw in ("patient contact", "skin contact", "blood", "wound", "implant")):
            set_field("patient_contact", True, notes="Heuristic extraction from contact keywords")
        if any(kw in lowered for kw in ("battery", "rechargeable", "usb", "powered", "electrical")):
            set_field("electrical_powered", True, notes="Heuristic extraction from power keywords")

        k_nums = re.findall(r"K\d{6}", full_text.upper())
        if k_nums:
            profile.user_predicate_mentions = ExtractedField.from_value(
                list(set(k_nums)),
                confidence=0.8,
                provenance=FieldProvenance.EXPLICIT,
                source_refs=source_ref,
                notes="Heuristic extraction of K-numbers",
            )

        profile.recompute_summary()
        return profile
