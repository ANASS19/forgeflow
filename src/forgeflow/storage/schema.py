"""SQLAlchemy mappings; schema changes require a new immutable migration."""

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    parent_id: Mapped[str | None]
    mode: Mapped[str]
    state: Mapped[str]
    created: Mapped[str] = mapped_column(index=True)
    ended: Mapped[str | None]
    plan: Mapped[str]
    event_count: Mapped[int] = mapped_column(default=0)
    recorded_bytes: Mapped[int] = mapped_column(default=0)


class StepRun(Base):
    __tablename__ = "step_runs"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    step_id: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int]
    kind: Mapped[str]
    state: Mapped[str]
    causes: Mapped[str] = mapped_column(default="[]")


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("run_id", "step_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str]
    number: Mapped[int]
    state: Mapped[str]
    code: Mapped[str | None]
    status_code: Mapped[int | None]
    duration: Mapped[float | None]
    retryable: Mapped[bool] = mapped_column(default=False)
    retry_delay: Mapped[float | None]


class RecordedValue(Base):
    __tablename__ = "recorded_values"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    step_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(primary_key=True)
    availability: Mapped[str]
    value: Mapped[str | None]


class Event(Base):
    __tablename__ = "events"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    sequence: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    step_id: Mapped[str | None]
    attempt: Mapped[int | None]
    timestamp: Mapped[str]
    payload: Mapped[str]
