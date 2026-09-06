#!/usr/bin/env python3
"""F07 rollback image retention policy (code/test contract; no VPS side effects).

Production may run under mutable deploy-prefixed tags such as
``sharipovai:deploy-<sha12>-<epoch>-<pid>``. Rollback must not assume
``sharipovai:<sha12>`` already exists.

Source of truth for the currently running release:
  1. the running container's image ID (``sha256:<64 hex>``)
  2. that image's OCI label ``org.opencontainers.image.revision``

Before a candidate build, retain the running image under the deterministic
rollback reference ``sharipovai:<sha12>`` only after the OCI revision matches
the expected previous commit SHA. Rollback redeploys that retained artifact
with ``docker compose up --no-build`` and never invokes ``docker compose build``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

OCI_REVISION_LABEL = "org.opencontainers.image.revision"
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class RollbackRetentionError(ValueError):
    """Fail-closed retention / verification error."""


def rollback_image_ref(sha: str) -> str:
    """Deterministic rollback tag derived from a full commit SHA."""
    if not FULL_SHA_RE.fullmatch(sha):
        raise RollbackRetentionError(f"expected full 40-char commit SHA, got {sha!r}")
    return f"sharipovai:{sha[:12]}"


def require_image_id(image_id: str | None) -> str:
    value = (image_id or "").strip()
    if not IMAGE_ID_RE.fullmatch(value):
        raise RollbackRetentionError(
            f"running container image ID missing or invalid: {image_id!r}"
        )
    return value


def require_matching_revision(expected_sha: str, actual_revision: str | None) -> str:
    if not FULL_SHA_RE.fullmatch(expected_sha):
        raise RollbackRetentionError(f"expected full 40-char commit SHA, got {expected_sha!r}")
    actual = (actual_revision or "").strip()
    if actual != expected_sha:
        raise RollbackRetentionError(
            "OCI revision mismatch: "
            f"expected {expected_sha}, got {actual or 'missing'}; "
            "refusing unreproducible rebuild"
        )
    return actual


@dataclass(frozen=True)
class RetentionPlan:
    expected_sha: str
    running_image_id: str
    current_tags: tuple[str, ...]
    rollback_ref: str
    oci_revision: str

    @property
    def uses_non_deterministic_tag(self) -> bool:
        return self.rollback_ref not in self.current_tags


def plan_retain_running_image(
    *,
    expected_sha: str,
    running_image_id: str | None,
    oci_revision: str | None,
    current_tags: list[str] | tuple[str, ...] | None = None,
) -> RetentionPlan:
    """Build a retention plan from the running container identity.

    Accepts differently-named current tags (e.g. ``deploy-*``) as long as the
    image ID's OCI revision matches ``expected_sha``. Tag alone is never enough.
    """
    image_id = require_image_id(running_image_id)
    revision = require_matching_revision(expected_sha, oci_revision)
    ref = rollback_image_ref(expected_sha)
    tags = tuple(tag for tag in (current_tags or ()) if tag)
    return RetentionPlan(
        expected_sha=expected_sha,
        running_image_id=image_id,
        current_tags=tags,
        rollback_ref=ref,
        oci_revision=revision,
    )


def assert_retained_artifact(
    *,
    expected_sha: str,
    artifact_present: bool,
    artifact_revision: str | None,
    artifact_image_id: str | None = None,
) -> str:
    """Fail closed unless the retained rollback artifact exists with matching revision."""
    ref = rollback_image_ref(expected_sha)
    if not artifact_present:
        raise RollbackRetentionError(
            f"retained rollback image {ref} is missing; refusing unreproducible rebuild"
        )
    require_matching_revision(expected_sha, artifact_revision)
    if artifact_image_id is not None:
        require_image_id(artifact_image_id)
    return ref


def reject_tag_only_trust(
    *,
    expected_sha: str,
    tagged_ref: str,
    oci_revision: str | None,
) -> None:
    """Arbitrary wrong images must not be accepted by tag alone."""
    expected_ref = rollback_image_ref(expected_sha)
    if tagged_ref != expected_ref:
        raise RollbackRetentionError(
            f"unexpected rollback tag {tagged_ref!r}; expected {expected_ref!r}"
        )
    require_matching_revision(expected_sha, oci_revision)


def labels_from_inspect(payload: Mapping[str, object]) -> dict[str, str]:
    config = payload.get("Config") if isinstance(payload.get("Config"), Mapping) else {}
    labels = config.get("Labels") if isinstance(config, Mapping) else None
    if not isinstance(labels, Mapping):
        return {}
    return {str(k): str(v) for k, v in labels.items() if v is not None}


def revision_from_inspect(payload: Mapping[str, object]) -> str | None:
    labels = labels_from_inspect(payload)
    value = labels.get(OCI_REVISION_LABEL)
    return value if value else None
