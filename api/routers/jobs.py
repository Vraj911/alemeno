import csv
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.config import settings
from api.database import get_db
from api.models import Job, JobStatus, JobSummary, Transaction
from api.schemas import (
    JobDetailResponse,
    JobListItem,
    JobResultsResponse,
    JobStatusResponse,
    JobSummaryFull,
    JobSummaryShort,
    JobUploadResponse,
    TopMerchant,
    TransactionResponse,
)
from worker.tasks import process_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

EXPECTED_HEADERS = {
    "txn_id",
    "date",
    "merchant",
    "amount",
    "currency",
    "status",
    "category",
    "account_id",
    "notes",
}


def _validate_csv(content: bytes, filename: str) -> tuple[list[dict[str, str]], int]:
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must have a .csv extension")

    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be valid UTF-8 text") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV has no header row")

    headers = {h.strip() for h in reader.fieldnames if h}
    missing = EXPECTED_HEADERS - headers
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV missing required columns: {', '.join(sorted(missing))}",
        )

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV contains no data rows")

    return rows, len(rows)


def _transaction_to_response(txn: Transaction) -> TransactionResponse:
    return TransactionResponse(
        id=txn.id,
        txn_id=txn.txn_id,
        original_txn_id_missing=txn.original_txn_id_missing,
        date=txn.date.isoformat() if txn.date else None,
        merchant=txn.merchant,
        amount=txn.amount,
        currency=txn.currency.value if txn.currency else None,
        status=txn.status.value if txn.status else None,
        category=txn.category,
        account_id=txn.account_id,
        is_anomaly=txn.is_anomaly,
        anomaly_reason=txn.anomaly_reason,
        llm_category=txn.llm_category,
        llm_failed=txn.llm_failed,
    )


@router.post(
    "/upload",
    response_model=JobUploadResponse,
    status_code=202,
    summary="Upload a CSV file for async processing",
    description="Validates the CSV, stores it on a shared volume, creates a job, and enqueues processing.",
)
async def upload_job(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    rows, row_count = _validate_csv(content, file.filename or "")

    job = Job(
        filename=file.filename or "upload.csv",
        status=JobStatus.pending,
        row_count_raw=row_count,
    )
    db.add(job)
    await db.flush()

    uploads_dir = Path(settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    csv_path = uploads_dir / f"{job.id}.csv"
    csv_path.write_bytes(content)

    await db.commit()

    process_job.delay(str(job.id))

    return JobUploadResponse(job_id=job.id, status=job.status.value)


@router.get(
    "/{job_id}/status",
    response_model=JobStatusResponse,
    summary="Get job processing status",
)
async def get_job_status(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).options(selectinload(Job.summary)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    response = JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        filename=job.filename,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
    )

    if job.status == JobStatus.completed and job.summary:
        response.summary = JobSummaryShort(
            total_spend_inr=job.summary.total_spend_inr,
            total_spend_usd=job.summary.total_spend_usd,
            anomaly_count=job.summary.anomaly_count,
            risk_level=job.summary.risk_level,
        )

    return response


@router.get(
    "/{job_id}/results",
    response_model=JobResultsResponse,
    summary="Get full job results",
    description="Returns cleaned transactions, anomalies, category breakdown, and LLM narrative summary.",
)
async def get_job_results(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.transactions), selectinload(Job.summary))
        .where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail="job not yet completed")

    transactions = [_transaction_to_response(t) for t in job.transactions]
    anomalies = [t for t in transactions if t.is_anomaly]

    category_breakdown: dict[str, float] = {}
    for txn in job.transactions:
        if txn.amount is not None:
            category_breakdown[txn.category] = category_breakdown.get(txn.category, 0) + float(
                txn.amount
            )

    summary = job.summary
    if summary is None:
        raise HTTPException(status_code=500, detail="Job completed but summary is missing")

    return JobResultsResponse(
        job=JobDetailResponse(
            job_id=job.id,
            status=job.status.value,
            filename=job.filename,
            row_count_raw=job.row_count_raw,
            row_count_clean=job.row_count_clean,
            created_at=job.created_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
        ),
        transactions=transactions,
        anomalies=anomalies,
        category_breakdown=category_breakdown,
        summary=JobSummaryFull(
            total_spend_inr=summary.total_spend_inr,
            total_spend_usd=summary.total_spend_usd,
            top_merchants=[TopMerchant(**m) for m in summary.top_merchants],
            anomaly_count=summary.anomaly_count,
            narrative=summary.narrative,
            risk_level=summary.risk_level,
        ),
    )


@router.get(
    "",
    response_model=list[JobListItem],
    summary="List all jobs",
    description="Supports filtering by status and pagination via limit/offset.",
)
async def list_jobs(
    status: JobStatus | None = Query(None, description="Filter by job status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Job).order_by(Job.created_at.desc()).offset(offset).limit(limit)
    if status is not None:
        query = query.where(Job.status == status)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return [
        JobListItem(
            job_id=j.id,
            filename=j.filename,
            status=j.status.value,
            row_count_raw=j.row_count_raw,
            created_at=j.created_at,
        )
        for j in jobs
    ]
