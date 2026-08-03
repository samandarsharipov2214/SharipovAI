"""Owner-gated development change controller.

Every AI-generated patch is persisted, reviewed by Security Guard, approved by
the configured Telegram owner and only then queued for the host wrapper.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .security_guard import SecurityGuard
from telegram_development_control import send_development_approval

_TERMINAL = {"rejected", "host_succeeded", "host_failed"}


@dataclass(slots=True)
class AgentDecision:
    decision_id: str
    short_id: str
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
    def __init__(self, *, state_file: str | Path | None = None, queue_dir: str | Path | None = None) -> None:
        data_dir = Path(os.getenv("SHARIPOVAI_DATA_DIR", "data"))
        self.state_file = Path(state_file or os.getenv("DEVELOPMENT_DECISIONS_FILE", data_dir / "development-decisions.json"))
        self.queue_dir = Path(queue_dir or os.getenv("DEVELOPMENT_HOST_QUEUE_DIR", data_dir / ".self_healing" / "development_queue"))
        self.guard = SecurityGuard()

    def submit_proposal(self, proposal: Mapping[str, Any]) -> AgentDecision:
        clean = _normalize_proposal(proposal)
        decision_id = hashlib.sha256(
            json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + secrets.token_bytes(16)
        ).hexdigest()
        now = int(time.time())
        decision = AgentDecision(
            decision_id=decision_id,
            short_id=decision_id[:12],
            status="submitted",
            proposal=clean,
            approval_token=secrets.token_urlsafe(12),
            created_at=now,
            updated_at=now,
        )
        self._save(decision)
        return decision

    def security_review(self, decision_id: str) -> AgentDecision:
        decision = self._get(decision_id)
        self._ensure_mutable(decision)
        patch = str(decision.proposal.get("patch", ""))
        verdict = self.guard.validate(patch)
        decision.security_verdict = {"allowed": verdict.allowed, "reasons": list(verdict.reasons)}
        decision.status = "security_approved" if verdict.allowed else "security_blocked"
        decision.updated_at = int(time.time())
        self._save(decision)
        return decision

    def request_owner_approval(self, decision_id: str) -> AgentDecision:
        decision = self._get(decision_id)
        if decision.status != "security_approved":
            raise RuntimeError("owner approval requires an allowed Security Guard verdict")
        response = send_development_approval(decision)
        result = response.get("result", {}) if isinstance(response, dict) else {}
        decision.status = "awaiting_owner"
        decision.owner_chat_id = str(result.get("chat", {}).get("id", os.getenv("TELEGRAM_OWNER_ID", "")))
        decision.updated_at = int(time.time())
        self._save(decision)
        return decision

    def decide(self, decision_id: str, approve: bool, actor_id: Any, chat_id: Any, token: str, reason: str) -> AgentDecision:
        decision = self._get(decision_id)
        if decision.status != "awaiting_owner":
            raise RuntimeError("decision is not awaiting owner approval")
        expected_owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
        actor = str(actor_id).strip()
        chat = str(chat_id).strip()
        if not expected_owner or actor != expected_owner or chat != expected_owner:
            raise PermissionError("only the configured Telegram owner may decide")
        if not hmac.compare_digest(str(token), decision.approval_token):
            raise PermissionError("invalid or expired development approval token")
        clean_reason = str(reason).strip()
        if not clean_reason:
            raise ValueError("reason is required")
        decision.owner_actor_id = actor
        decision.owner_chat_id = chat
        decision.reason = clean_reason[:1000]
        decision.approval_token = ""
        decision.status = "owner_approved" if approve else "rejected"
        decision.updated_at = int(time.time())
        self._save(decision)
        return decision

    def queue_host_application(self, decision_id: str) -> AgentDecision:
        decision = self._get(decision_id)
        if decision.status != "owner_approved":
            raise RuntimeError("host application requires explicit owner approval")
        if decision.security_verdict.get("allowed") is not True:
            raise RuntimeError("Security Guard did not allow this patch")
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "decision_id": decision.decision_id,
            "short_id": decision.short_id,
            "proposal": decision.proposal,
            "security_verdict": decision.security_verdict,
            "owner_actor_id": decision.owner_actor_id,
            "owner_chat_id": decision.owner_chat_id,
            "owner_reason": decision.reason,
            "queued_at": int(time.time()),
        }
        target = self.queue_dir / f"{decision.decision_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        decision.status = "queued_for_host"
        decision.updated_at = int(time.time())
        self._save(decision)
        return decision

    def record_host_result(self, decision_id: str, result: Mapping[str, Any]) -> AgentDecision:
        decision = self._get(decision_id)
        if decision.status not in {"queued_for_host", "host_applying"}:
            raise RuntimeError("host result is not valid in the current state")
        clean = dict(result)
        success = clean.get("success") is True or clean.get("status") in {"ok", "success", "applied"}
        decision.host_result = clean
        decision.status = "host_succeeded" if success else "host_failed"
        decision.updated_at = int(time.time())
        self._save(decision)
        return decision

    def _get(self, decision_id: str) -> AgentDecision:
        key = str(decision_id).strip()
        records = self._load()
        if key in records:
            return AgentDecision(**records[key])
        matches = [value for value in records.values() if str(value.get("short_id")) == key]
        if len(matches) != 1:
            raise KeyError(f"development decision not found: {key}")
        return AgentDecision(**matches[0])

    def _ensure_mutable(self, decision: AgentDecision) -> None:
        if decision.status in _TERMINAL:
            raise RuntimeError(f"development decision is terminal: {decision.status}")

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save(self, decision: AgentDecision) -> None:
        records = self._load()
        records[decision.decision_id] = decision.to_dict()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.state_file)


def _normalize_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(proposal, Mapping):
        raise TypeError("proposal must be a mapping")
    clean = dict(proposal)
    patch = clean.get("patch")
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("proposal.patch must contain a unified diff")
    files = clean.get("changed_files") or clean.get("files") or []
    if not isinstance(files, list):
        raise ValueError("proposal.changed_files must be a list")
    clean["changed_files"] = [str(item) for item in files][:100]
    clean["patch"] = patch
    return clean


__all__ = ["AgentDecision", "DevelopmentChangeController"]
