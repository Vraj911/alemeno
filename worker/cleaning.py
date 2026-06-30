import logging
import re
import uuid
from datetime import date, datetime
from typing import Any
import pandas as pd
logger = logging.getLogger(__name__)
VALID_CURRENCIES = {"INR", "USD"}
VALID_STATUSES = {"SUCCESS", "FAILED", "PENDING"}
def _parse_date(value: Any) -> tuple[date | None, str | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, "unparseable_date"
    text = str(value).strip()
    if not text:
        return None, "unparseable_date"
    formats = ("%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            continue
    logger.warning("Unparseable date: %s", text)
    return None, "unparseable_date"
def _parse_amount(value: Any) -> tuple[float | None, str | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, "unparseable_amount"
    text = str(value).strip()
    if not text:
        return None, "unparseable_amount"
    cleaned = re.sub(r"[$,\s]", "", text)
    try:
        return float(cleaned), None
    except ValueError:
        logger.warning("Unparseable amount: %s", value)
        return None, "unparseable_amount"
def _normalize_currency(value: Any) -> tuple[str | None, str | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, "invalid_currency"
    currency = str(value).strip().upper()
    if currency in VALID_CURRENCIES:
        return currency, None
    return currency if currency else None, "invalid_currency"
def _normalize_status(value: Any) -> tuple[str | None, str | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, "invalid_status"
    status = str(value).strip().upper()
    if status in VALID_STATUSES:
        return status, None
    return status if status else None, "invalid_status"
def _clean_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()
def clean_transactions(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Clean raw CSV rows. Returns cleaned dataframe and duplicate drop count."""
    raw_cols = [
        "txn_id",
        "date",
        "merchant",
        "amount",
        "currency",
        "status",
        "category",
        "account_id",
        "notes",
    ]
    before = len(df)
    df = df.drop_duplicates(subset=raw_cols, keep="first").reset_index(drop=True)
    duplicates_dropped = before - len(df)
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        anomaly_flags: list[str] = []
        raw_txn_id = _clean_str(row.get("txn_id"))
        original_txn_id_missing = not raw_txn_id
        txn_id = raw_txn_id or f"GEN-{uuid.uuid4().hex[:8]}"
        parsed_date, date_flag = _parse_date(row.get("date"))
        if date_flag:
            anomaly_flags.append(date_flag)
        amount, amount_flag = _parse_amount(row.get("amount"))
        if amount_flag:
            anomaly_flags.append(amount_flag)
        currency, currency_flag = _normalize_currency(row.get("currency"))
        if currency_flag:
            anomaly_flags.append(currency_flag)
        status, status_flag = _normalize_status(row.get("status"))
        if status_flag:
            anomaly_flags.append(status_flag)
        category_raw = _clean_str(row.get("category"))
        category = category_raw if category_raw else None
        merchant = _clean_str(row.get("merchant"))
        account_id = _clean_str(row.get("account_id"))
        notes = _clean_str(row.get("notes"))
        rows.append(
            {
                "txn_id": txn_id,
                "original_txn_id_missing": original_txn_id_missing,
                "date": parsed_date,
                "merchant": merchant,
                "amount": amount,
                "currency": currency,
                "status": status,
                "category": category,
                "account_id": account_id,
                "notes": notes,
                "is_anomaly": bool(anomaly_flags),
                "anomaly_reason": ",".join(anomaly_flags) if anomaly_flags else None,
                "llm_category": None,
                "llm_raw_response": None,
                "llm_failed": False,
            }
        )
    cleaned_df = pd.DataFrame(rows)
    return cleaned_df, duplicates_dropped
