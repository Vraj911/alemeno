import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import settings
from api.models import Currency, Job, JobStatus, JobSummary, Transaction, TransactionStatus
from worker.anomaly import detect_anomalies
from worker.celery_app import celery_app
from worker.cleaning import clean_transactions
from worker.llm import classify_transactions, compute_stats, generate_narrative

logger = logging.getLogger(__name__)


def _get_async_session() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _process_job_async(job_id: str) -> None:
    session_factory = _get_async_session()

    async with session_factory() as db:
        job_uuid = uuid.UUID(job_id)
        result = await db.execute(select(Job).where(Job.id == job_uuid))
        job = result.scalar_one_or_none()
        if job is None:
            logger.error("Job %s not found", job_id)
            return

        try:
            job.status = JobStatus.processing
            await db.commit()

            csv_path = Path(settings.uploads_dir) / f"{job_id}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(f"CSV file not found at {csv_path}")

            df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
            cleaned_df, _duplicates_dropped = clean_transactions(df)
            cleaned_df = detect_anomalies(cleaned_df)
            cleaned_df = await classify_transactions(cleaned_df)

            stats = compute_stats(cleaned_df)
            narrative_result = await generate_narrative(cleaned_df, stats)

            job.row_count_clean = len(cleaned_df)
            job.status = JobStatus.completed
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = None

            for _, row in cleaned_df.iterrows():
                currency = row.get("currency")
                status = row.get("status")

                txn = Transaction(
                    job_id=job.id,
                    txn_id=row["txn_id"],
                    original_txn_id_missing=bool(row["original_txn_id_missing"]),
                    date=row["date"] if pd.notna(row.get("date")) else None,
                    merchant=row["merchant"],
                    amount=row["amount"] if pd.notna(row.get("amount")) else None,
                    currency=Currency(currency) if currency in {"INR", "USD"} else None,
                    status=TransactionStatus(status) if status in {"SUCCESS", "FAILED", "PENDING"} else None,
                    category=row["category"] or "Uncategorised",
                    account_id=row["account_id"] or "",
                    is_anomaly=bool(row["is_anomaly"]),
                    anomaly_reason=row["anomaly_reason"] if pd.notna(row.get("anomaly_reason")) else None,
                    llm_category=row["llm_category"] if pd.notna(row.get("llm_category")) else None,
                    llm_raw_response=row["llm_raw_response"] if pd.notna(row.get("llm_raw_response")) else None,
                    llm_failed=bool(row["llm_failed"]),
                )
                db.add(txn)

            summary = JobSummary(
                job_id=job.id,
                total_spend_inr=stats["total_spend_inr"],
                total_spend_usd=stats["total_spend_usd"],
                top_merchants=stats["top_merchants"],
                anomaly_count=stats["anomaly_count"],
                narrative=narrative_result["narrative"],
                risk_level=narrative_result["risk_level"],
            )
            db.add(summary)

            await db.commit()
            logger.info("Job %s completed successfully", job_id)

        except Exception as exc:
            logger.exception("Job %s failed: %s", job_id, exc)
            await db.rollback()

            result = await db.execute(select(Job).where(Job.id == job_uuid))
            job = result.scalar_one_or_none()
            if job:
                job.status = JobStatus.failed
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()


@celery_app.task(name="worker.tasks.process_job")
def process_job(job_id: str) -> None:
    asyncio.run(_process_job_async(job_id))
