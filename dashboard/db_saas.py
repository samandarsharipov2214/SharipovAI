"""Database helpers for the SharipovAI SaaS layer."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, select
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
    created = 0
    try:
        existing_ids = select(AccessRequest.user_id)
        users = db.scalars(
            select(User).where(User.is_active.is_(False), User.id.not_in(existing_ids))
        ).all()
        for user in users:
            db.add(AccessRequest(
                user_id=user.id,
                contact="",
                reason="Migrated legacy inactive account; original request metadata unavailable.",
                created_at=user.created_at,
            ))
            created += 1
        db.commit()
        return created
    except Exception:
        db.rollback()
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
