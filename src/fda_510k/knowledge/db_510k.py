from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from rapidfuzz import fuzz

from fda_510k.config import settings


@dataclass
class Device510kRecord:
    k_number: str
    device_name: str
    applicant: str
    product_code: str
    decision_code: str | None
    decision_date: date | None
    clearance_type: str | None
    statement_or_summary: str | None
    advisory_committee: str | None
    regulation_number: str | None
    device_class: str | None
    openfda_device_name: str | None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _row_to_record(row: sqlite3.Row) -> Device510kRecord:
    return Device510kRecord(
        k_number=row["k_number"],
        device_name=row["device_name"] or "",
        applicant=row["applicant"] or "",
        product_code=row["product_code"] or "",
        decision_code=row["decision_code"],
        decision_date=_parse_date(row["decision_date"]),
        clearance_type=row["clearance_type"],
        statement_or_summary=row["statement_or_summary"],
        advisory_committee=row["advisory_committee"],
        regulation_number=row["regulation_number"],
        device_class=row["device_class"],
        openfda_device_name=row["openfda_device_name"],
    )


class Device510kRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.fda_510k_db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self.db_path.exists():
                raise FileNotFoundError(
                    f"510(k) database not found at {self.db_path}. "
                    "Run: python scripts/import_510k_db.py"
                )
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get_by_k_number(self, k_number: str) -> Device510kRecord | None:
        k = k_number.upper().strip()
        if not k.startswith("K"):
            k = f"K{k}"
        row = self.conn.execute(
            "SELECT * FROM devices_510k WHERE k_number = ?",
            (k,),
        ).fetchone()
        return _row_to_record(row) if row else None

    def search(
        self,
        *,
        product_code: str | None = None,
        regulation_number: str | None = None,
        device_class: str | None = None,
        advisory_committee: str | None = None,
        query_text: str | None = None,
        limit: int = 50,
    ) -> list[Device510kRecord]:
        clauses: list[str] = []
        params: list[str] = []

        if product_code:
            clauses.append("product_code = ?")
            params.append(product_code.upper())
        if regulation_number:
            clauses.append("regulation_number = ?")
            params.append(regulation_number)
        if device_class:
            clauses.append("device_class = ?")
            params.append(device_class)
        if advisory_committee:
            clauses.append("advisory_committee = ?")
            params.append(advisory_committee.upper())

        if query_text:
            terms = [term for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{1,}", query_text) if len(term) >= 2]
            fts_query = " OR ".join(f'"{term}"' for term in terms[:12]) if terms else f'"{query_text}"'
            sql = """
                SELECT d.* FROM devices_510k d
                JOIN devices_510k_fts fts ON d.id = fts.rowid
                WHERE devices_510k_fts MATCH ?
            """
            params_fts = [fts_query]
            if clauses:
                sql += " AND " + " AND ".join(clauses)
                params_fts.extend(params)
            sql += " ORDER BY d.decision_date DESC LIMIT ?"
            params_fts.append(str(limit))
            rows = self.conn.execute(sql, params_fts).fetchall()
        elif clauses:
            sql = (
                f"SELECT * FROM devices_510k WHERE {' AND '.join(clauses)} "
                "ORDER BY decision_date DESC LIMIT ?"
            )
            params.append(str(limit))
            rows = self.conn.execute(sql, params).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM devices_510k ORDER BY decision_date DESC LIMIT ?",
                (str(limit),),
            ).fetchall()

        return [_row_to_record(r) for r in rows]

    def search_by_name_fuzzy(
        self, name: str, *, product_code: str | None = None, limit: int = 20
    ) -> list[tuple[Device510kRecord, float]]:
        candidates = self.search(product_code=product_code, query_text=name, limit=limit * 3)
        if not candidates:
            candidates = self.search(query_text=name, limit=limit * 3)

        scored: list[tuple[Device510kRecord, float]] = []
        for rec in candidates:
            score = max(
                fuzz.token_set_ratio(name.lower(), rec.device_name.lower()),
                fuzz.token_set_ratio(name.lower(), (rec.openfda_device_name or "").lower()),
            )
            scored.append((rec, score / 100.0))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def rank_candidates(
        self,
        *,
        device_name: str,
        product_code: str | None = None,
        regulation_number: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[Device510kRecord, float, dict[str, float]]]:
        records = self.search(
            product_code=product_code,
            regulation_number=regulation_number,
            query_text=device_name,
            limit=100,
        )
        if not records and product_code:
            records = self.search(query_text=device_name, limit=100)
        if not records:
            records = self.search(query_text=device_name, limit=100)

        today = date.today()
        ranked: list[tuple[Device510kRecord, float, dict[str, float]]] = []

        for rec in records:
            name_sim = max(
                fuzz.token_set_ratio(device_name.lower(), rec.device_name.lower()),
                fuzz.token_set_ratio(device_name.lower(), (rec.openfda_device_name or "").lower()),
            ) / 100.0

            pc_match = 1.0 if product_code and rec.product_code == product_code.upper() else 0.0
            if not product_code and regulation_number and rec.regulation_number == regulation_number:
                pc_match = 0.5

            if rec.decision_date:
                years_ago = (today - rec.decision_date).days / 365.25
                recency = max(0.0, 1.0 - years_ago / 30.0)
            else:
                recency = 0.0

            has_summary = 1.0 if rec.statement_or_summary == "Summary" else 0.3
            sese = 1.0 if rec.decision_code == "SESE" else 0.5

            signals = {
                "product_code_match": pc_match,
                "name_similarity": name_sim,
                "recency": recency,
                "has_summary": has_summary,
                "sese": sese,
            }
            score = (
                0.35 * pc_match
                + 0.25 * name_sim
                + 0.20 * recency
                + 0.10 * has_summary
                + 0.10 * sese
            )
            ranked.append((rec, score, signals))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
