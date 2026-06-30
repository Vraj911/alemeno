"""Initial schema
Revision ID: 001
Revises:
Create Date: 2026-06-30
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
job_status = postgresql.ENUM(
    "pending", "processing", "completed", "failed", name="job_status", create_type=False
)
currency_enum = postgresql.ENUM("INR", "USD", name="currency_enum", create_type=False)
transaction_status = postgresql.ENUM(
    "SUCCESS", "FAILED", "PENDING", name="transaction_status", create_type=False
)
def upgrade() -> None:
    op.execute("CREATE TYPE job_status AS ENUM ('pending', 'processing', 'completed', 'failed')")
    op.execute("CREATE TYPE currency_enum AS ENUM ('INR', 'USD')")
    op.execute("CREATE TYPE transaction_status AS ENUM ('SUCCESS', 'FAILED', 'PENDING')")
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("row_count_raw", sa.Integer(), nullable=True),
        sa.Column("row_count_clean", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("txn_id", sa.String(length=64), nullable=False),
        sa.Column("original_txn_id_missing", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("merchant", sa.String(length=256), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", currency_enum, nullable=True),
        sa.Column("status", transaction_status, nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("anomaly_reason", sa.Text(), nullable=True),
        sa.Column("llm_category", sa.String(length=64), nullable=True),
        sa.Column("llm_raw_response", sa.Text(), nullable=True),
        sa.Column("llm_failed", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_job_id", "transactions", ["job_id"])
    op.create_table(
        "job_summaries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("total_spend_inr", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_spend_usd", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("top_merchants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("anomaly_count", sa.Integer(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
def downgrade() -> None:
    op.drop_table("job_summaries")
    op.drop_index("ix_transactions_job_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("jobs")
    op.execute("DROP TYPE transaction_status")
    op.execute("DROP TYPE currency_enum")
    op.execute("DROP TYPE job_status")
