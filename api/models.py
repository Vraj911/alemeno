import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Currency(str, enum.Enum):
    INR = "INR"
    USD = "USD"


class TransactionStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=JobStatus.pending,
    )
    row_count_raw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count_clean: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    summary: Mapped["JobSummary | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    txn_id: Mapped[str] = mapped_column(String(64), nullable=False)
    original_txn_id_missing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    merchant: Mapped[str] = mapped_column(String(256), nullable=False)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Currency | None] = mapped_column(
        Enum(Currency, name="currency_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    status: Mapped[TransactionStatus | None] = mapped_column(
        Enum(
            TransactionStatus,
            name="transaction_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_failed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="transactions")


class JobSummary(Base):
    __tablename__ = "job_summaries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    total_spend_inr: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_spend_usd: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    top_merchants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    anomaly_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")

    job: Mapped["Job"] = relationship(back_populates="summary")
