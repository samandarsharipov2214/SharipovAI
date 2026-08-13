"""Database-backed owner gate for AI-generated development patches.

The canonical source of truth is ``ProjectDatabase``. Files under the persistent
self-healing directory are transport envelopes only; they never replace the
``agent_fixes``, ``agent_decisions`` and ``agent_decision_events`` ledger.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from storage import ProjectDatabase
from telegram_development_control import send_development_approval

from .security_guard import SecurityGuard

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_TERMINAL = {"rejected", "applied", "failed", "rolled_back"}
_CRITICAL_ACTIONS = frozenset({"restore_database", "git_revert"})


@dataclass(slots=True)
class DevelopmentDecision:
    decision_id: str
    short_id: str
    fix_id: str
    status: str
    proposal: dict[str, Any]
    security_verdict: dict[str, Any] = field(default_factory=dict)
    approval_token: str = ""
    owner_actor_id: str = ""
    owner_chat_id: str = ""
    reason: str = ""
    host_result: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DevelopmentChangeController:
    """Orchestrate security review, owner approval and host queue creation."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        queue_dir: str | Path | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        data_dir = Path(os.getenv("SHARIPOVAI_DATA_DIR", "data"))
        self.queue_dir = Path(
            queue_dir
            or os.getenv(
                "DEVELOPMENT_HOST_QUEUE_DIR",
                data_dir / ".self_healing",
            )
        )
        self.guard = SecurityGuard()

    def submit_proposal(self, proposal: Mapping[str, Any]) -> DevelopmentDecision:
        clean = _normalize_proposal(proposal)
        patch = str(clean["patch"])
        base_sha = _base_sha(clean)
        target_branch = str(clean.get("target_branch") or "main").strip()
        patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        entropy = secrets.token_bytes(16)
        material = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
        decision_id = hashlib.sha256(material + entropy).hexdigest()
        fix_id = f"fix_{decision_id}"
        now = int(time.time() * 1000)
        approval_token = secrets.token_urlsafe(18)
        metadata = {
            "schema_version": 1,
            "proposal": clean,
            "security_verdict": {},
            "approval_token": approval_token,
            "owner_actor_id": "",
            "owner_chat_id": "",
            "owner_reason": "",
            "host_result": {},
        }
        self.database.record_agent_fix(
            fix_id=fix_id,
            error_signature=str(clean.get("error") or clean.get("failure") or "development_change"),
            failure_class="development_change_proposal",
            patch=patch,
            success=False,
            source=str(clean.get("source") or "general_controller"),
            base_sha=base_sha,
            test_evidence=clean.get("test_results") or clean.get("tests") or {},
            metadata={"decision_id": decision_id, "changed_files": clean["changed_files"]},
            created_at_ms=now,
        )
        self.database.record_agent_decision(
            decision_id=decision_id,
            fix_id=fix_id,
            kind="propose",
            status="submitted",
            base_sha=base_sha,
            target_branch=target_branch,
            patch_sha256=patch_sha256,
            security_verdict="not_evaluated",
            actor="general_controller",
            rationale=str(clean.get("error") or "AI-generated development proposal"),
            metadata=metadata,
            created_at_ms=now,
        )
        self.database.append_agent_decision_event(
            decision_id=decision_id,
            event_type="submitted",
            actor="general_controller",
            payload={"fix_id": fix_id, "patch_sha256": patch_sha256},
            created_at_ms=now,
        )
        return self.get(decision_id)

    def submit_critical_action(
        self,
        action: str,
        *,
        reason: str,
        base_sha: str,
        details: Mapping[str, Any] | None = None,
    ) -> DevelopmentDecision:
        """Create an owner-gated, non-patch destructive-action decision."""

        clean_action = str(action).strip()
        if clean_action not in _CRITICAL_ACTIONS:
            raise ValueError("unsupported critical self-healing action")
        proposal = {
            "critical_action": clean_action,
            "reason": str(reason).strip(),
            "details": dict(details or {}),
            "base_sha": str(base_sha).strip().lower(),
            "target_branch": "main",
            "source": "self_healing_agent",
            "changed_files": [],
            # The existing immutable fix ledger requires non-empty patch evidence.
            # Store a canonical action manifest here; critical actions never pass it
            # to git apply because queue_host_application routes them separately.
            "patch": json.dumps({"critical_action": clean_action}, sort_keys=True, separators=(",", ":")),
        }
        return self.submit_proposal(proposal)

    def get(self, decision_id: str) -> DevelopmentDecision:
        row = self._find_decision(decision_id)
        return _decision_from_row(row)

    def security_review(self, decision_id: str) -> DevelopmentDecision:
        decision = self.get(decision_id)
        self._ensure_mutable(decision)
        critical_action = str(decision.proposal.get("critical_action") or "")
        if critical_action:
            if critical_action not in _CRITICAL_ACTIONS:
                raise RuntimeError("unsupported critical self-healing action")
            verdict_payload = {
                "allowed": True,
                "reasons": ["allow-listed critical action requires Telegram owner approval"],
                "policy_version": "development-v2",
            }
        else:
            verdict = self.guard.evaluate(str(decision.proposal.get("patch", "")))
            verdict_payload = verdict.model_dump(mode="json") if hasattr(verdict, "model_dump") else {
                "allowed": bool(verdict.allowed),
                "reasons": list(verdict.reasons),
            }
        status = "security_approved" if verdict_payload["allowed"] else "security_blocked"
        self._transition(
            decision.decision_id,
            status=status,
            security_verdict="allow" if verdict_payload["allowed"] else "block",
            event_type=status,
            actor="security_guard",
            metadata_updates={"security_verdict": verdict_payload},
            event_payload=verdict_payload,
        )
        return self.get(decision.decision_id)

    def request_owner_approval(self, decision_id: str) -> DevelopmentDecision:
        decision = self.get(decision_id)
        if decision.status != "security_approved" or decision.security_verdict.get("allowed") is not True:
            raise RuntimeError("owner approval requires an allowed Security Guard verdict")
        response = send_development_approval(decision)
        result = response.get("result", {}) if isinstance(response, dict) else {}
        chat_id = str(result.get("chat", {}).get("id", os.getenv("TELEGRAM_OWNER_ID", "")))
        self._transition(
            decision.decision_id,
            status="awaiting_owner",
            security_verdict="allow",
            event_type="owner_approval_requested",
            actor="general_controller",
            metadata_updates={"owner_chat_id": chat_id},
            event_payload={"owner_chat_id": chat_id},
        )
        return self.get(decision.decision_id)

    def decide(
        self,
        decision_id: str,
        approve: bool,
        actor_id: Any,
        chat_id: Any,
        token: str,
        reason: str,
    ) -> DevelopmentDecision:
        decision = self.get(decision_id)
        if decision.status != "awaiting_owner":
            raise RuntimeError("decision is not awaiting owner approval")
        expected_owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
        actor = str(actor_id).strip()
        chat = str(chat_id).strip()
        if not expected_owner or actor != expected_owner or chat != expected_owner:
            raise PermissionError("only the configured Telegram owner may decide")
        if not decision.approval_token or not hmac.compare_digest(str(token), decision.approval_token):
            raise PermissionError("invalid or expired development approval token")
        clean_reason = str(reason).strip()
        if not clean_reason:
            raise ValueError("reason is required")
        status = "approved" if approve else "rejected"
        self._transition(
            decision.decision_id,
            status=status,
            security_verdict="allow",
            event_type="owner_approved" if approve else "owner_rejected",
            actor=f"telegram:{actor}",
            rationale=clean_reason[:1000],
            metadata_updates={
                "approval_token": "",
                "owner_actor_id": actor,
                "owner_chat_id": chat,
                "owner_reason": clean_reason[:1000],
            },
            event_payload={"approved": bool(approve), "actor_id": actor, "reason": clean_reason[:1000]},
        )
        return self.get(decision.decision_id)

    def queue_host_application(self, decision_id: str) -> DevelopmentDecision:
        decision = self.get(decision_id)
        if decision.status != "approved":
            raise RuntimeError("host application requires explicit owner approval")
        if decision.security_verdict.get("allowed") is not True:
            raise RuntimeError("Security Guard did not allow this patch")

        critical_action = str(decision.proposal.get("critical_action") or "")
        if critical_action:
            return self._queue_critical_action(decision, critical_action)

        patch = str(decision.proposal.get("patch", ""))
        patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        row = self.database.get_agent_decision(decision.decision_id)
        if row is None or row["patch_sha256"] != patch_sha256:
            raise RuntimeError("patch evidence no longer matches the canonical decision")

        self.queue_dir.mkdir(parents=True, exist_ok=True)
        patch_path = self.queue_dir / f"approved-{decision.decision_id}.patch"
        manifest_path = self.queue_dir / "approved_patch.json"
        action_path = self.queue_dir / "action"
        action_json_path = self.queue_dir / "action.json"
        manifest = {
            "decision_id": decision.decision_id,
            "base_sha": row["base_sha"],
            "patch_sha256": patch_sha256,
            "patch_container_path": str(patch_path),
        }
        action_payload = {
            "action": "apply_approved_patch",
            "decision_id": decision.decision_id,
            "created_at_ms": int(time.time() * 1000),
        }
        _atomic_write(patch_path, patch)
        _atomic_write(manifest_path, json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
        _atomic_write(action_json_path, json.dumps(action_payload, sort_keys=True, separators=(",", ":")) + "\n")
        _atomic_write(action_path, "apply_approved_patch\n")
        self.database.append_agent_decision_event(
            decision_id=decision.decision_id,
            event_type="queued_for_host",
            actor="general_controller",
            payload={"manifest_path": str(manifest_path), "patch_sha256": patch_sha256},
        )
        return self.get(decision.decision_id)

    def claim_critical_action(self, decision_id: str, action: str) -> DevelopmentDecision:
        """Consume one owner-approved destructive action before host execution."""

        decision = self.get(decision_id)
        if decision.status != "approved":
            raise RuntimeError("critical action is not awaiting one-shot execution")
        expected = str(decision.proposal.get("critical_action") or "")
        if action not in _CRITICAL_ACTIONS or action != expected:
            raise PermissionError("critical action does not match approved decision")
        owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
        if not owner or decision.owner_actor_id != owner or decision.owner_chat_id != owner:
            raise PermissionError("critical action approval lacks configured owner evidence")
        self._transition(
            decision.decision_id,
            status="executing",
            security_verdict="allow",
            event_type="critical_action_claimed",
            actor="self-healing-run",
            metadata_updates={},
            event_payload={"action": action},
        )
        return self.get(decision.decision_id)

    def _queue_critical_action(self, decision: DevelopmentDecision, action: str) -> DevelopmentDecision:
        if action not in _CRITICAL_ACTIONS:
            raise RuntimeError("unsupported critical self-healing action")
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        action_path = self.queue_dir / "action"
        action_json_path = self.queue_dir / "action.json"
        expected_sha_path = self.queue_dir / "expected_sha"
        action_payload = {
            "action": action,
            "approval_decision_id": decision.decision_id,
            "expected_sha": str(decision.proposal.get("base_sha") or ""),
            "details": dict(decision.proposal.get("details") or {}),
            "created_at_ms": int(time.time() * 1000),
        }
        _atomic_write(action_json_path, json.dumps(action_payload, sort_keys=True, separators=(",", ":")) + "\n")
        _atomic_write(expected_sha_path, action_payload["expected_sha"] + "\n")
        _atomic_write(action_path, action + "\n")
        self.database.append_agent_decision_event(
            decision_id=decision.decision_id,
            event_type="critical_action_queued",
            actor="general_controller",
            payload={"action": action},
        )
        return self.get(decision.decision_id)

    def record_host_result(self, decision_id: str, result: Mapping[str, Any]) -> DevelopmentDecision:
        decision = self.get(decision_id)
        # Destructive actions transition to ``executing`` when their one-shot
        # owner approval is consumed.  The host must be able to write exactly
        # one terminal outcome from that state; otherwise the canonical audit
        # ledger permanently misreports a completed critical action as running.
        if decision.status not in {"approved", "executing", "applied", "failed"}:
            raise RuntimeError("host result is not valid in the current state")
        clean = dict(result)
        if decision.status in {"applied", "failed"}:
            previous = decision.host_result
            if previous == clean:
                # A host may retry reporting after a transport failure.  Preserve
                # the original immutable terminal event rather than appending a
                # second, indistinguishable completion record.
                return decision
            raise RuntimeError("host result conflicts with the terminal audit record")
        success = clean.get("success") is True or clean.get("status") in {"ok", "success", "applied"}
        self._transition(
            decision.decision_id,
            status="applied" if success else "failed",
            security_verdict="allow",
            event_type="host_applied" if success else "host_failed",
            actor="self-healing-run",
            metadata_updates={"host_result": clean},
            event_payload=clean,
        )
        return self.get(decision.decision_id)

    def _find_decision(self, decision_id: str) -> dict[str, Any]:
        key = str(decision_id).strip()
        exact = self.database.get_agent_decision(key) if len(key) > 12 else None
        if exact is not None:
            return exact
        if len(key) != 12 or any(character not in "0123456789abcdef" for character in key.lower()):
            raise KeyError(f"development decision not found: {key}")
        with self.database.connect() as connection:
            rows = self.database._fetchall(  # noqa: SLF001 - canonical repository adapter
                connection,
                """
                SELECT decision_id FROM agent_decisions
                WHERE decision_id LIKE ? ORDER BY created_at_ms DESC LIMIT 2
                """,
                (f"{key.lower()}%",),
            )
        if len(rows) != 1:
            raise KeyError(f"development decision not found or ambiguous: {key}")
        found = self.database.get_agent_decision(str(rows[0]["decision_id"]))
        if found is None:
            raise KeyError(f"development decision not found: {key}")
        return found

    def _ensure_mutable(self, decision: DevelopmentDecision) -> None:
        if decision.status in _TERMINAL:
            raise RuntimeError(f"development decision is terminal: {decision.status}")

    def _transition(
        self,
        decision_id: str,
        *,
        status: str,
        security_verdict: str,
        event_type: str,
        actor: str,
        metadata_updates: Mapping[str, Any],
        event_payload: Mapping[str, Any],
        rationale: str | None = None,
    ) -> None:
        now = int(time.time() * 1000)
        event_id = hashlib.sha256(
            f"{decision_id}\0{event_type}\0{now}\0{secrets.token_hex(8)}".encode("utf-8")
        ).hexdigest()
        with self.database.connect() as connection:
            try:
                self.database._begin(connection, immediate=True)  # noqa: SLF001
                row = self.database._fetchone(  # noqa: SLF001
                    connection,
                    "SELECT metadata_json, rationale FROM agent_decisions WHERE decision_id = ?",
                    (decision_id,),
                    lock=True,
                )
                if row is None:
                    raise KeyError(f"development decision not found: {decision_id}")
                metadata = json.loads(row["metadata_json"])
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata.update(dict(metadata_updates))
                self.database._execute(  # noqa: SLF001
                    connection,
                    """
                    UPDATE agent_decisions
                    SET status = ?, security_verdict = ?, actor = ?, rationale = ?,
                        metadata_json = ?, updated_at_ms = ?
                    WHERE decision_id = ?
                    """,
                    (
                        status,
                        security_verdict,
                        actor,
                        rationale if rationale is not None else row["rationale"],
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        now,
                        decision_id,
                    ),
                )
                self.database._execute(  # noqa: SLF001
                    connection,
                    """
                    INSERT INTO agent_decision_events(
                        event_id, decision_id, event_type, actor, payload_json, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        decision_id,
                        event_type,
                        actor,
                        json.dumps(dict(event_payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        now,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _decision_from_row(row: Mapping[str, Any]) -> DevelopmentDecision:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    proposal = metadata.get("proposal") if isinstance(metadata.get("proposal"), Mapping) else {}
    verdict = metadata.get("security_verdict") if isinstance(metadata.get("security_verdict"), Mapping) else {}
    created_at_ms = int(row.get("created_at_ms") or 0)
    updated_at_ms = int(row.get("updated_at_ms") or 0)
    decision_id = str(row["decision_id"])
    return DevelopmentDecision(
        decision_id=decision_id,
        short_id=decision_id[:12],
        fix_id=str(row.get("fix_id") or ""),
        status=str(row.get("status") or ""),
        proposal=dict(proposal),
        security_verdict=dict(verdict),
        approval_token=str(metadata.get("approval_token") or ""),
        owner_actor_id=str(metadata.get("owner_actor_id") or ""),
        owner_chat_id=str(metadata.get("owner_chat_id") or ""),
        reason=str(metadata.get("owner_reason") or row.get("rationale") or ""),
        host_result=dict(metadata.get("host_result") or {}) if isinstance(metadata.get("host_result"), Mapping) else {},
        created_at=created_at_ms,
        updated_at=updated_at_ms,
    )


def _normalize_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(proposal, Mapping):
        raise TypeError("proposal must be a mapping")
    clean = dict(proposal)
    critical_action = str(clean.get("critical_action") or "")
    patch = clean.get("patch")
    if critical_action in _CRITICAL_ACTIONS and patch == "":
        clean["critical_action"] = critical_action
    elif not isinstance(patch, str) or not patch.strip():
        raise ValueError("proposal.patch must contain a unified diff")
    files = clean.get("changed_files") or clean.get("files") or []
    if not isinstance(files, (list, tuple)):
        raise ValueError("proposal.changed_files must be a list")
    clean["changed_files"] = [str(item) for item in files][:100]
    clean["patch"] = patch
    return clean


def _base_sha(proposal: Mapping[str, Any]) -> str:
    value = str(
        proposal.get("base_sha")
        or proposal.get("source_head")
        or os.getenv("SHARIPOVAI_BUILD_SHA", "")
    ).strip().lower()
    if not _SHA40.fullmatch(value):
        raise ValueError("proposal must contain a lowercase 40-character base_sha/source_head")
    return value


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


__all__ = ["DevelopmentChangeController", "DevelopmentDecision"]
