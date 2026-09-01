from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import dashboard.db_saas as db_saas
from dashboard.models_saas import AccessRequest, Base, User
import storage


def test_legacy_inactive_users_are_backfilled_idempotently(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(User(email="legacy@example.test", display_name="Legacy", password_hash="hash", is_active=False))
        db.add(User(email="active@example.test", display_name="Active", password_hash="hash", is_active=True))
        db.commit()
    monkeypatch.setattr(db_saas, "SessionLocal", sessions)
    events = []

    class Ledger:
        def create_change(self, **kwargs):
            events.append(("planned", kwargs))
        def set_status(self, _change_id, status, **kwargs):
            events.append((status, kwargs))

    monkeypatch.setattr(storage, "ProjectChangeLedger", Ledger)

    assert db_saas.backfill_legacy_inactive_access_requests() == 1
    assert db_saas.backfill_legacy_inactive_access_requests() == 0
    with sessions() as db:
        request = db.scalar(select(AccessRequest))
        user = db.scalar(select(User).where(User.email == "legacy@example.test"))
        assert request.user_id == user.id
        assert request.status == "pending"
        assert request.contact == ""
        assert "Migrated legacy inactive" in request.reason
        assert user.is_active is False
    assert [event[0] for event in events] == ["planned", "applied", "verified"]
