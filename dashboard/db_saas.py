"""Database helpers for the SharipovAI SaaS layer."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models_saas import AccessRequest, Base, User
from .settings_saas import get_saas_settings

_settings = get_saas_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine = create_engine(_settings.database_url, future=True, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def init_saas_database() -> None:
    Base.metadata.create_all(bind=engine)
    backfill_legacy_inactive_access_requests()


def backfill_legacy_inactive_access_requests() -> int:
    """Make pre-Site-V1 inactive accounts actionable without activating them.

    This is deliberately idempotent and records only known provenance: the
    original user creation timestamp; contact and reason were not collected by
    the legacy flow and are left empty rather than invented.
    """
    db = SessionLocal()
    ledger = None
    created = 0
    try:
        existing_ids = select(AccessRequest.user_id)
        users = db.scalars(
            select(User).where(User.is_active.is_(False), User.id.not_in(existing_ids))
        ).all()
        if not users:
            return 0
        from storage import ProjectChangeLedger
        ledger = ProjectChangeLedger()
        change_id = f"saas-access-request-backfill-{uuid4().hex}"
        ledger.create_change(
            change_id=change_id,
            summary="Backfill canonical access requests for legacy inactive SaaS users",
            actor="dashboard.db_saas",
            operations=[{
                "kind": "create",
                "path": "dashboard/models_saas.py",
                "ownership": "managed",
                "reason": "legacy inactive user approval queue backfill",
            }],
            metadata={"candidate_count": len(users)},
        )
        for user in users:
            # A savepoint makes a unique collision from another startup worker
            # harmless while retaining all other backfill work in this batch.
            try:
                with db.begin_nested():
                    db.add(AccessRequest(
                        user_id=user.id,
                        contact="",
                        reason="Migrated legacy inactive account; original request metadata unavailable.",
                        created_at=user.created_at,
                    ))
                    db.flush()
                    created += 1
            except IntegrityError:
                continue
        db.commit()
        ledger.set_status(change_id, "applied", actor="dashboard.db_saas", verification={"created_count": created})
        ledger.set_status(change_id, "verified", actor="dashboard.db_saas", verification={"created_count": created})
        return created
    except Exception:
        db.rollback()
        if ledger is not None:
            try:
                ledger.set_status(change_id, "failed", actor="dashboard.db_saas", note="backfill transaction failed")
            except Exception:
                pass
        raise
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = ["SessionLocal", "backfill_legacy_inactive_access_requests", "engine", "get_db", "init_saas_database", "session_scope"]
