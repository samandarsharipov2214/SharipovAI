"""Evidence Vault for SharipovAI.

Stores decisions, evidence sources, outcomes and source reputation in SQLite.
It allows the system to replay why a decision was made and learn from the
result without inventing facts after the fact.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


DEFAULT_DB = "data/evidence_vault.sqlite3"


def default_evidence_db_path() -> Path:
    return Path(os.getenv("EVIDENCE_VAULT_DB", DEFAULT_DB))


class EvidenceVault:
    """SQLite-backed decision evidence memory."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_evidence_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record_decision(
        self,
        *,
        actor: str,
        decision: str,
        topic: str,
        confidence: float,
        risk_level: str,
        reason: str,
        evidence: list[dict[str, Any]] | None = None,
        policy_status: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store one AI decision and its evidence."""

        now = int(time.time())
        decision_id = _decision_id(actor, decision, topic, reason, now)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO decisions(decision_id, actor, decision, topic, confidence, risk_level, reason, policy_status, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    _norm(actor),
                    decision.strip().upper(),
                    topic.strip().lower(),
                    float(confidence),
                    risk_level.strip().upper(),
                    reason.strip(),
                    policy_status.strip().lower(),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
            for item in evidence or []:
                self._insert_evidence(conn, decision_id, item, now)
        return {"status": "ok", "decision_id": decision_id}

    def add_outcome(
        self,
        *,
        decision_id: str,
        outcome: str,
        impact_score: float,
        notes: str = "",
        learning_signal: str = "neutral",
    ) -> dict[str, Any]:
        """Attach an outcome to a past decision and update source reputation."""

        replay = self.replay_decision(decision_id)
        if replay.get("status") != "ok":
            return {"status": "not_found", "decision_id": decision_id}
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO outcomes(decision_id, outcome, impact_score, notes, learning_signal, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (decision_id, outcome.strip().lower(), float(impact_score), notes.strip(), learning_signal.strip().lower(), now),
            )
            evidence_rows = conn.execute("SELECT source_domain FROM evidence WHERE decision_id = ?", (decision_id,)).fetchall()
            for row in evidence_rows:
                _update_reputation(conn, row["source_domain"], float(impact_score), learning_signal.strip().lower(), now)
        return {"status": "ok", "decision_id": decision_id, "outcome": outcome, "impact_score": float(impact_score)}

    def replay_decision(self, decision_id: str) -> dict[str, Any]:
        """Return the exact saved decision context."""

        with self._connect() as conn:
            decision = conn.execute("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
            if decision is None:
                return {"status": "not_found", "decision_id": decision_id}
            evidence = [_row(row) for row in conn.execute("SELECT * FROM evidence WHERE decision_id = ? ORDER BY id", (decision_id,)).fetchall()]
            outcomes = [_row(row) for row in conn.execute("SELECT * FROM outcomes WHERE decision_id = ? ORDER BY created_at DESC, id DESC", (decision_id,)).fetchall()]
        record = _row(decision)
        record["metadata"] = _safe_json(record.pop("metadata_json", "{}"))
        return {"status": "ok", "decision": record, "evidence": evidence, "outcomes": outcomes, "replay": _replay_text(record, evidence, outcomes)}

    def source_reputation(self, source_domain: str | None = None) -> dict[str, Any]:
        """Return source reputation table."""

        with self._connect() as conn:
            if source_domain:
                rows = conn.execute("SELECT * FROM source_reputation WHERE source_domain = ?", (_domain(source_domain),)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM source_reputation ORDER BY trust_score DESC, uses DESC").fetchall()
        return {"status": "ok", "sources": [_row(row) for row in rows]}

    def decisions(self, *, limit: int = 50, actor: str | None = None) -> list[dict[str, Any]]:
        """List recent decisions."""

        with self._connect() as conn:
            if actor:
                rows = conn.execute(
                    "SELECT * FROM decisions WHERE actor = ? ORDER BY created_at DESC LIMIT ?",
                    (_norm(actor), int(limit)),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [_decision_row(row) for row in rows]

    def snapshot(self) -> dict[str, Any]:
        """Return Evidence Vault dashboard snapshot."""

        with self._connect() as conn:
            decision_count = int(conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])
            evidence_count = int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
            outcome_count = int(conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0])
            source_count = int(conn.execute("SELECT COUNT(*) FROM source_reputation").fetchone()[0])
        recent = self.decisions(limit=20)
        reputation = self.source_reputation().get("sources", [])[:20]
        return {
            "status": "ok",
            "decision_count": decision_count,
            "evidence_count": evidence_count,
            "outcome_count": outcome_count,
            "source_count": source_count,
            "recent_decisions": recent,
            "source_reputation": reputation,
        }

    def _insert_evidence(self, conn: sqlite3.Connection, decision_id: str, item: dict[str, Any], now: int) -> None:
        domain = _domain(str(item.get("source_domain", item.get("domain", "unknown"))))
        conn.execute(
            "INSERT INTO evidence(decision_id, source_title, source_domain, source_type, url, trust_score, summary, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision_id,
                str(item.get("title", "Untitled")),
                domain,
                str(item.get("source_type", "unknown")),
                str(item.get("url", "")),
                float(item.get("trust_score", 50.0)),
                str(item.get("summary", "")),
                int(item.get("checked_at", now) or now),
            ),
        )
        _ensure_reputation(conn, domain, float(item.get("trust_score", 50.0)), now)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT UNIQUE NOT NULL, actor TEXT NOT NULL, decision TEXT NOT NULL, topic TEXT NOT NULL, confidence REAL NOT NULL, risk_level TEXT NOT NULL, reason TEXT NOT NULL, policy_status TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL, source_title TEXT NOT NULL, source_domain TEXT NOT NULL, source_type TEXT NOT NULL, url TEXT NOT NULL, trust_score REAL NOT NULL, summary TEXT NOT NULL, checked_at INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS outcomes(id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL, outcome TEXT NOT NULL, impact_score REAL NOT NULL, notes TEXT NOT NULL, learning_signal TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS source_reputation(source_domain TEXT PRIMARY KEY, trust_score REAL NOT NULL, uses INTEGER NOT NULL, confirmed INTEGER NOT NULL, contradicted INTEGER NOT NULL, last_seen_at INTEGER NOT NULL)"
            )


def _ensure_reputation(conn: sqlite3.Connection, domain: str, trust_score: float, now: int) -> None:
    row = conn.execute("SELECT * FROM source_reputation WHERE source_domain = ?", (domain,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO source_reputation(source_domain, trust_score, uses, confirmed, contradicted, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
            (domain, max(0.0, min(100.0, trust_score)), 1, 0, 0, now),
        )
    else:
        conn.execute(
            "UPDATE source_reputation SET uses = uses + 1, last_seen_at = ? WHERE source_domain = ?",
            (now, domain),
        )


def _update_reputation(conn: sqlite3.Connection, domain: str, impact_score: float, learning_signal: str, now: int) -> None:
    _ensure_reputation(conn, domain, 50.0, now)
    row = conn.execute("SELECT * FROM source_reputation WHERE source_domain = ?", (domain,)).fetchone()
    trust = float(row["trust_score"])
    confirmed = int(row["confirmed"])
    contradicted = int(row["contradicted"])
    if learning_signal in {"positive", "confirmed", "good"} or impact_score > 0:
        trust = min(100.0, trust + 3.0)
        confirmed += 1
    elif learning_signal in {"negative", "contradicted", "bad"} or impact_score < 0:
        trust = max(0.0, trust - 7.0)
        contradicted += 1
    conn.execute(
        "UPDATE source_reputation SET trust_score = ?, confirmed = ?, contradicted = ?, last_seen_at = ? WHERE source_domain = ?",
        (trust, confirmed, contradicted, now, domain),
    )


def _decision_id(actor: str, decision: str, topic: str, reason: str, created_at: int) -> str:
    raw = f"{actor}|{decision}|{topic}|{reason}|{created_at}"
    return "DEC-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _norm(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _domain(value: str) -> str:
    clean = value.strip().lower().replace("https://", "").replace("http://", "")
    return clean.split("/")[0] or "unknown"


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _decision_row(row: sqlite3.Row) -> dict[str, Any]:
    record = _row(row)
    record["metadata"] = _safe_json(record.pop("metadata_json", "{}"))
    return record


def _safe_json(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _replay_text(decision: dict[str, Any], evidence: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> str:
    source_names = ", ".join(str(item.get("source_domain", "unknown")) for item in evidence) or "no sources"
    outcome_text = str(outcomes[0].get("outcome", "not measured yet")) if outcomes else "not measured yet"
    return (
        f"Actor {decision.get('actor')} decided {decision.get('decision')} on {decision.get('topic')} "
        f"with confidence {decision.get('confidence')} and risk {decision.get('risk_level')}. "
        f"Reason: {decision.get('reason')}. Sources: {source_names}. Outcome: {outcome_text}."
    )
