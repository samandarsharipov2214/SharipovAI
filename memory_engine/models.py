"""SQLAlchemy table declarations and validated API schemas for Memory Layer."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import BigInteger, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MemoryStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class RawLogStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class MemoryBase(DeclarativeBase):
    pass


class MemoryRawLogORM(MemoryBase):
    __tablename__ = "memory_raw_logs"

    log_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(200), index=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    agent_id: Mapped[str] = mapped_column(String(200), index=True)
    session_id: Mapped[str] = mapped_column(String(200), index=True)
    message_role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(String(500))
    source_digest: Mapped[str] = mapped_column(String(64), unique=True)
    processing_status: Mapped[str] = mapped_column(String(32), default=RawLogStatus.PENDING.value)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    processed_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class MemoryFactORM(MemoryBase):
    __tablename__ = "memory_facts"
    __table_args__ = (
        UniqueConstraint("team_id", "agent_id", "user_id", "source_digest", name="memory_fact_source_uq"),
    )

    fact_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(200), index=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    agent_id: Mapped[str] = mapped_column(String(200), index=True)
    session_id: Mapped[str] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text)
    background: Mapped[str] = mapped_column(Text, default="")
    fact_type: Mapped[str] = mapped_column(String(64), default="work_fact")
    status: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    source_log_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_ref: Mapped[str] = mapped_column(String(500), default="")
    source_digest: Mapped[str] = mapped_column(String(64))
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    updated_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)


class MemoryScenarioORM(MemoryBase):
    __tablename__ = "memory_scenarios"
    __table_args__ = (
        UniqueConstraint("team_id", "agent_id", "user_id", "name", "version", name="memory_scenario_version_uq"),
    )

    scenario_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(200), index=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    agent_id: Mapped[str] = mapped_column(String(200), index=True)
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    updated_at_ms: Mapped[int] = mapped_column(BigInteger)


class MemoryCoreORM(MemoryBase):
    __tablename__ = "memory_core"
    __table_args__ = (
        UniqueConstraint("team_id", "agent_id", "user_id", "version", name="memory_core_version_uq"),
    )

    core_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(200), index=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    agent_id: Mapped[str] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    updated_at_ms: Mapped[int] = mapped_column(BigInteger)


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RawLogCreate(_Schema):
    team_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    agent_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    message_role: str = Field(default="event", min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=100_000)
    source_ref: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at_ms: int | None = Field(default=None, gt=0)


class RawLog(_Schema):
    log_id: str
    team_id: str
    user_id: str
    agent_id: str
    session_id: str
    message_role: str
    content: str
    source_ref: str
    source_digest: str
    processing_status: RawLogStatus
    metadata: dict[str, Any]
    created_at_ms: int
    processed_at_ms: int | None = None


class FactCreate(_Schema):
    team_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    agent_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)
    background: str = Field(default="", max_length=20_000)
    fact_type: str = Field(default="work_fact", min_length=1, max_length=64)
    priority: int = Field(default=50, ge=0, le=100)
    source_log_id: str | None = Field(default=None, max_length=200)
    source_ref: str = Field(default="", max_length=500)
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if not value or len(value) > 8192:
            raise ValueError("embedding must contain 1..8192 values")
        return [float(item) for item in value]


class MemoryFact(_Schema):
    fact_id: str
    team_id: str
    user_id: str
    agent_id: str
    session_id: str
    content: str
    background: str
    fact_type: str
    status: MemoryStatus
    priority: int
    source_log_id: str | None
    source_ref: str
    source_digest: str
    embedding: list[float] | None
    metadata: dict[str, Any]
    created_at_ms: int
    updated_at_ms: int


class ContextItem(_Schema):
    fact_id: str
    content: str
    background: str
    fact_type: str
    status: MemoryStatus
    priority: int
    score: float
    source_ref: str


class ContextRequest(_Schema):
    agent_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    query_text: str = Field(min_length=1, max_length=20_000)
    team_id: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)


class ApprovalRequest(_Schema):
    actor: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)
    manual_approval: bool = False


__all__ = [
    "ApprovalRequest",
    "ContextItem",
    "ContextRequest",
    "FactCreate",
    "MemoryBase",
    "MemoryCoreORM",
    "MemoryFact",
    "MemoryFactORM",
    "MemoryScenarioORM",
    "MemoryStatus",
    "RawLog",
    "RawLogCreate",
    "RawLogStatus",
]
