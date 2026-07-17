from __future__ import annotations

import pytest

from storage import ProjectChangeLedger, ProjectDatabase, VersionConflict


def _ledger(tmp_path) -> ProjectChangeLedger:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    return ProjectChangeLedger(database)


def test_change_lifecycle_is_database_backed(tmp_path) -> None:
    ledger = _ledger(tmp_path)

    created = ledger.create_change(
        change_id="ecc-foundation-1",
        summary="Add evidence-backed project governance",
        actor="github-agent",
        operations=[
            {
                "kind": "create",
                "path": "storage/change_ledger.py",
                "ownership": "managed",
                "digest_after": "sha256:example",
            }
        ],
        metadata={"source": "affaan-m/ECC", "mode": "adapted-not-copied"},
        created_at_ms=1000,
    )

    assert created["status"] == "planned"
    assert created["version"] == 1
    applied = ledger.set_status(
        "ecc-foundation-1",
        "applied",
        actor="github-agent",
        expected_version=1,
        updated_at_ms=2000,
    )
    verified = ledger.set_status(
        "ecc-foundation-1",
        "verified",
        actor="github-actions",
        verification={"pytest": "passed", "commit": "abc123"},
        expected_version=applied["version"],
        updated_at_ms=3000,
    )

    assert verified["status"] == "verified"
    assert verified["verification"]["pytest"] == "passed"
    assert ledger.get_change("ecc-foundation-1")["version"] == 3
    history = ledger.history("ecc-foundation-1")
    assert [item["payload"]["action"] for item in history] == [
        "status_changed",
        "status_changed",
        "created",
    ]


def test_change_ledger_rejects_unsafe_paths_and_sensitive_metadata(tmp_path) -> None:
    ledger = _ledger(tmp_path)

    with pytest.raises(ValueError, match="repository-relative"):
        ledger.create_change(
            change_id="unsafe-path",
            summary="Unsafe path must be rejected",
            actor="test",
            operations=[{"kind": "delete", "path": "../secrets.env"}],
        )

    with pytest.raises(ValueError, match="sensitive metadata key"):
        ledger.create_change(
            change_id="unsafe-metadata",
            summary="Secrets must never enter the evidence ledger",
            actor="test",
            operations=[{"kind": "update", "path": "README.md"}],
            metadata={"api_token": "must-not-be-stored"},
        )


def test_change_ledger_uses_optimistic_versions(tmp_path) -> None:
    ledger = _ledger(tmp_path)
    ledger.create_change(
        change_id="versioned-change",
        summary="Protect concurrent updates",
        actor="test",
        operations=[{"kind": "configuration", "path": "render.yaml", "ownership": "shared"}],
    )

    with pytest.raises(VersionConflict, match="version mismatch"):
        ledger.set_status(
            "versioned-change",
            "applied",
            actor="test",
            expected_version=99,
        )


def test_verified_change_cannot_return_to_planned(tmp_path) -> None:
    ledger = _ledger(tmp_path)
    created = ledger.create_change(
        change_id="immutable-verification",
        summary="Verification cannot be silently reset",
        actor="test",
        operations=[{"kind": "update", "path": "AGENTS.md"}],
    )
    applied = ledger.set_status(
        "immutable-verification",
        "applied",
        actor="test",
        expected_version=created["version"],
    )
    verified = ledger.set_status(
        "immutable-verification",
        "verified",
        actor="test",
        expected_version=applied["version"],
    )

    with pytest.raises(ValueError, match="invalid change transition"):
        ledger.set_status(
            "immutable-verification",
            "planned",
            actor="test",
            expected_version=verified["version"],
        )
