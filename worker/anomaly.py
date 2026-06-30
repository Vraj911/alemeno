import logging

import pandas as pd

logger = logging.getLogger(__name__)

DOMESTIC_ONLY_BRANDS = ["Swiggy", "Ola", "IRCTC"]


def _append_reason(existing: str | None, reason: str) -> str:
    if not existing:
        return reason
    reasons = [r.strip() for r in existing.split(",") if r.strip()]
    if reason not in reasons:
        reasons.append(reason)
    return ",".join(reasons)


def _is_domestic_brand(merchant: str) -> bool:
    merchant_lower = merchant.lower()
    return any(brand.lower() in merchant_lower for brand in DOMESTIC_ONLY_BRANDS)


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Flag statistical outliers, currency mismatches, and suspicious notes."""
    result = df.copy()

    # Statistical outlier: amount > 3x account median
    # Median works for groups of any size (including 1-2 transactions).
    medians = result.groupby("account_id")["amount"].transform("median")

    for idx, row in result.iterrows():
        amount = row.get("amount")
        median = medians.loc[idx]
        if amount is not None and median is not None and not pd.isna(median) and median > 0:
            if float(amount) > 3 * float(median):
                result.at[idx, "is_anomaly"] = True
                result.at[idx, "anomaly_reason"] = _append_reason(
                    result.at[idx, "anomaly_reason"], "statistical_outlier"
                )

        merchant = str(row.get("merchant", ""))
        currency = row.get("currency")
        if currency == "USD" and _is_domestic_brand(merchant):
            result.at[idx, "is_anomaly"] = True
            result.at[idx, "anomaly_reason"] = _append_reason(
                result.at[idx, "anomaly_reason"], "currency_mismatch"
            )

        notes = str(row.get("notes", ""))
        notes_upper = notes.upper()
        if "SUSPICIOUS" in notes_upper:
            result.at[idx, "is_anomaly"] = True
            result.at[idx, "anomaly_reason"] = _append_reason(
                result.at[idx, "anomaly_reason"], "suspicious_note"
            )
        if "DUPLICATE?" in notes_upper:
            result.at[idx, "is_anomaly"] = True
            result.at[idx, "anomaly_reason"] = _append_reason(
                result.at[idx, "anomaly_reason"], "duplicate_note"
            )

    return result
