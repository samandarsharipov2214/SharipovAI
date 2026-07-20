"""SQLAlchemy models for SharipovAI SaaS authentication and billing."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "saas_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    free_messages_limit: Mapped[int] = mapped_column(Integer, default=25)
    messages_used_this_period: Mapped[int] = mapped_column(Integer, default=0)
    current_period_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    subscription: Mapped[Subscription | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    chat_messages: Mapped[list[ChatMessageLog]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Subscription(Base):
    __tablename__ = "saas_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("saas_users.id", ondelete="CASCADE"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(24), default="stripe")
    plan_code: Mapped[str] = mapped_column(String(64), default="free")
    status: Mapped[str] = mapped_column(String(32), default="free")
    provider_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="subscription")


class ChatMessageLog(Base):
    __tablename__ = "saas_chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("saas_users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="gemini")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="chat_messages")


__all__ = ["Base", "ChatMessageLog", "Subscription", "User", "utcnow"]
