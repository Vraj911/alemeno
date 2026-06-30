import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any
import httpx
import pandas as pd
from api.config import settings
logger = logging.getLogger(__name__)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
VALID_CATEGORIES = {
    "Food",
    "Shopping",
    "Travel",
    "Transport",
    "Utilities",
    "Cash Withdrawal",
    "Entertainment",
    "Other",
}
CLASSIFICATION_BATCH_SIZE = 30
async def _call_openrouter(
    system_prompt: str, user_prompt: str, max_tokens: int = 4096
) -> str:
    if not settings.openrouter_api_key or settings.openrouter_api_key == "your_openrouter_api_key_here":
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
def _extract_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)
async def retry_llm_call(
    call_fn: Callable[[], Any],
    max_attempts: int = 3,
) -> tuple[Any | None, str | None, Exception | None]:
    """Retry with exponential backoff: 2**attempt seconds (1s, 2s, 4s)."""
    last_error: Exception | None = None
    raw_response: str | None = None
    for attempt in range(max_attempts):
        try:
            result = await call_fn()
            if isinstance(result, str):
                raw_response = result[:2000]
                parsed = _extract_json(result)
            else:
                parsed = result
                raw_response = json.dumps(parsed)[:2000]
            return parsed, raw_response, None
        except Exception as exc:
            last_error = exc
            logger.warning("LLM call attempt %s failed: %s", attempt + 1, exc)
            if attempt < max_attempts - 1:
                await asyncio.sleep(2**attempt)
    return None, raw_response, last_error
def _chunk_indices(indices: list[int], size: int) -> list[list[int]]:
    return [indices[i : i + size] for i in range(0, len(indices), size)]
async def classify_transactions(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    needs_category = result["category"].isna() | (result["category"] == "")
    indices = result.index[needs_category].tolist()
    if not indices:
        return result
    system_prompt = (
        "You are a financial transaction classifier. "
        "Respond with JSON only — no markdown fences, no preamble, no explanation. "
        "Return a JSON object mapping txn_id to category. "
        "Each category must be exactly one of: "
        "Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other."
    )
    for batch_indices in _chunk_indices(indices, CLASSIFICATION_BATCH_SIZE):
        batch = result.loc[batch_indices]
        transactions = []
        for _, row in batch.iterrows():
            transactions.append(
                {
                    "txn_id": row["txn_id"],
                    "merchant": row["merchant"],
                    "amount": row["amount"],
                    "currency": row["currency"],
                    "notes": row["notes"],
                }
            )
        user_prompt = (
            "Classify each transaction below. "
            f"Return JSON object mapping txn_id to category.\n\n"
            f"{json.dumps(transactions, default=str)}"
        )
        async def _do_call() -> str:
            return await _call_openrouter(system_prompt, user_prompt)
        parsed, raw_response, error = await retry_llm_call(_do_call)
        if error or not isinstance(parsed, dict):
            logger.error("Classification batch failed after retries: %s", error)
            for idx in batch_indices:
                result.at[idx, "category"] = "Uncategorised"
                result.at[idx, "llm_failed"] = True
                if raw_response:
                    result.at[idx, "llm_raw_response"] = raw_response
            continue
        for idx in batch_indices:
            txn_id = result.at[idx, "txn_id"]
            category = parsed.get(txn_id, "Other")
            if category not in VALID_CATEGORIES:
                category = "Other"
            result.at[idx, "category"] = category
            result.at[idx, "llm_category"] = category
            if raw_response:
                result.at[idx, "llm_raw_response"] = raw_response
    return result
def compute_stats(df: pd.DataFrame) -> dict[str, Any]:
    success_mask = df["status"] == "SUCCESS"
    success_df = df[success_mask]
    total_spend_inr = float(
        success_df.loc[success_df["currency"] == "INR", "amount"].fillna(0).sum()
    )
    total_spend_usd = float(
        success_df.loc[success_df["currency"] == "USD", "amount"].fillna(0).sum()
    )
    merchant_stats = (
        success_df.groupby("merchant")
        .agg(total_amount=("amount", "sum"), txn_count=("txn_id", "count"))
        .reset_index()
        .sort_values("total_amount", ascending=False)
        .head(3)
    )
    top_merchants = [
        {
            "merchant": row["merchant"],
            "total_amount": round(float(row["total_amount"]), 2),
            "txn_count": int(row["txn_count"]),
        }
        for _, row in merchant_stats.iterrows()
    ]
    anomaly_count = int(df["is_anomaly"].sum())
    return {
        "total_spend_inr": round(total_spend_inr, 2),
        "total_spend_usd": round(total_spend_usd, 2),
        "top_merchants": top_merchants,
        "anomaly_count": anomaly_count,
    }
def _fallback_risk_level(df: pd.DataFrame, stats: dict[str, Any]) -> str:
    anomaly_count = stats["anomaly_count"]
    if anomaly_count > 5:
        return "high"
    medians = df.groupby("account_id")["amount"].median()
    for _, row in df.iterrows():
        amount = row.get("amount")
        account_id = row.get("account_id")
        if amount is None or not account_id:
            continue
        median = medians.get(account_id)
        if median is not None and not pd.isna(median) and median > 0:
            if float(amount) > 5 * float(median):
                return "high"
    if anomaly_count > 0:
        return "medium"
    return "low"
def _fallback_narrative(stats: dict[str, Any]) -> str:
    top = stats["top_merchants"]
    top_names = ", ".join(m["merchant"] for m in top[:3]) if top else "N/A"
    return (
        f"Processed transactions with total spend of INR {stats['total_spend_inr']:,.2f} "
        f"and USD {stats['total_spend_usd']:,.2f}. "
        f"Top merchants by spend: {top_names}. "
        f"Detected {stats['anomaly_count']} anomalous transaction(s)."
    )
async def generate_narrative(df: pd.DataFrame, stats: dict[str, Any]) -> dict[str, str]:
    sample = df.head(15)[
        ["txn_id", "merchant", "amount", "currency", "category", "is_anomaly"]
    ].to_dict(orient="records")
    system_prompt = (
        "You are a financial analyst. Respond with JSON only — no markdown fences, no preamble. "
        'Return exactly: {"narrative": "<2-3 sentence summary>", "risk_level": "low|medium|high"}. '
        "The narrative must reference actual numbers and merchant names from the provided data."
    )
    user_prompt = json.dumps(
        {
            "stats": stats,
            "sample_transactions": sample,
        },
        default=str,
    )
    async def _do_call() -> str:
        return await _call_openrouter(system_prompt, user_prompt)
    parsed, _, error = await retry_llm_call(_do_call)
    if error or not isinstance(parsed, dict):
        logger.error("Narrative generation failed after retries: %s", error)
        return {
            "narrative": _fallback_narrative(stats),
            "risk_level": _fallback_risk_level(df, stats),
        }
    narrative = parsed.get("narrative") or _fallback_narrative(stats)
    risk_level = parsed.get("risk_level", "low")
    if risk_level not in {"low", "medium", "high"}:
        risk_level = _fallback_risk_level(df, stats)
    return {"narrative": narrative, "risk_level": risk_level}
