from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
class JobUploadResponse(BaseModel):
    job_id: UUID
    status: str
class JobSummaryShort(BaseModel):
    total_spend_inr: Decimal
    total_spend_usd: Decimal
    anomaly_count: int
    risk_level: str
class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    filename: str
    row_count_raw: int | None
    row_count_clean: int | None
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    summary: JobSummaryShort | None = None
class JobListItem(BaseModel):
    job_id: UUID
    filename: str
    status: str
    row_count_raw: int | None
    created_at: datetime
class TopMerchant(BaseModel):
    merchant: str
    total_amount: Decimal
    txn_count: int
class JobSummaryFull(BaseModel):
    total_spend_inr: Decimal
    total_spend_usd: Decimal
    top_merchants: list[TopMerchant]
    anomaly_count: int
    narrative: str
    risk_level: str
class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    txn_id: str
    original_txn_id_missing: bool
    date: str | None
    merchant: str
    amount: Decimal | None
    currency: str | None
    status: str | None
    category: str
    account_id: str
    is_anomaly: bool
    anomaly_reason: str | None
    llm_category: str | None
    llm_failed: bool
class JobDetailResponse(BaseModel):
    job_id: UUID
    status: str
    filename: str
    row_count_raw: int | None
    row_count_clean: int | None
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
class JobResultsResponse(BaseModel):
    job: JobDetailResponse
    transactions: list[TransactionResponse]
    anomalies: list[TransactionResponse]
    category_breakdown: dict[str, Decimal]
    summary: JobSummaryFull
