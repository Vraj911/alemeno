# AI-Powered Transaction Processing Pipeline

A production-style backend that ingests dirty financial transaction CSVs, processes them asynchronously through Celery, cleans and normalizes data, detects anomalies, classifies missing categories via OpenRouter LLM, and returns structured spending summaries through a polling REST API.

## Architecture

```
Client → FastAPI (POST /jobs/upload)
           ↓ save CSV to shared volume + Job row (pending)
           ↓ enqueue Celery task
         Redis broker
           ↓
         Celery Worker (5-step pipeline)
           1. Data cleaning (dates, amounts, dedup)
           2. Anomaly detection (outliers, currency mismatch, notes)
           3. LLM batch classification (missing categories)
           4. LLM narrative summary
           5. Persist transactions + JobSummary → PostgreSQL
           ↓
Client polls GET /jobs/{id}/status → GET /jobs/{id}/results
```

**Services:** `api` (FastAPI + Alembic migrations), `worker` (Celery), `redis`, `postgres`

## Setup

1. Clone the repository.
2. Copy environment template and add your OpenRouter API key:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set `OPENROUTER_API_KEY` to your key from [OpenRouter](https://openrouter.ai/).
3. Start everything:
   ```bash
   docker compose up --build
   ```
4. API available at `http://localhost:8000` — interactive docs at `http://localhost:8000/docs`.

Migrations run automatically on API startup (`alembic upgrade head` in the entrypoint).

## Example API Usage

### 1. Upload CSV

```bash
curl -X POST "http://localhost:8000/jobs/upload" \
  -H "accept: application/json" \
  -F "file=@transactions.csv"
```

Response (`202 Accepted`):
```json
{"job_id": "a1b2c3d4-...", "status": "pending"}
```

### 2. Poll status until completed

```bash
curl "http://localhost:8000/jobs/{job_id}/status"
```

When complete, response includes a short `summary`:
```json
{
  "job_id": "...",
  "status": "completed",
  "filename": "transactions.csv",
  "row_count_raw": 94,
  "row_count_clean": 82,
  "created_at": "...",
  "completed_at": "...",
  "summary": {
    "total_spend_inr": 123456.78,
    "total_spend_usd": 9876.54,
    "anomaly_count": 15,
    "risk_level": "high"
  }
}
```

### 3. Fetch full results

```bash
curl "http://localhost:8000/jobs/{job_id}/results"
```

Returns cleaned transactions, anomaly subset, per-category spend breakdown, and full LLM narrative.

### 4. List jobs

```bash
# All jobs (paginated, default limit=20)
curl "http://localhost:8000/jobs"

# Filter by status
curl "http://localhost:8000/jobs?status=completed&limit=10&offset=0"
```

## Design Decisions

**Shared volume for CSV handoff:** Uploaded files are saved to `/data/uploads/{job_id}.csv` on a Docker named volume mounted in both `api` and `worker`. This avoids bloating the database with raw file bytes and keeps the Celery message payload small (only the job UUID).

**Batched LLM calls:** Rows missing a category are collected and sent in a single prompt per batch (~30 rows), not one API call per row. This cuts latency, cost, and rate-limit risk dramatically on ~90-row files.

**Retry with exponential backoff:** Both classification and narrative LLM calls use a shared retry wrapper — up to 3 attempts with `2^attempt` second delays (1s, 2s, 4s). JSON parse failures and HTTP errors trigger retries.

**Partial LLM failure:** If classification fails after all retries, affected rows get `category="Uncategorised"` and `llm_failed=true`, but the job still completes. Narrative failure falls back to a deterministic Python-generated summary and rule-based `risk_level`. Only genuine pipeline errors (missing file, DB failure) mark the job as `failed`.

## Known Limitations / What I'd Change at Scale

- **Connection pooling:** Each Celery task currently creates its own async engine. At scale, use a shared pool or switch worker DB access to sync SQLAlchemy with a properly sized pool.
- **Worker autoscaling:** A single Celery worker won't keep up with concurrent uploads. Add multiple worker replicas and consider queue-based autoscaling (K8s HPA on queue depth).
- **Upload path:** Move CSV intake to presigned S3/GCS URLs so the API never handles large file bodies directly.
- **Queue splitting:** Separate Celery queues for classification vs. narrative with different priorities — classification blocks results visibility, narrative is nice-to-have for the summary endpoint.
- **Idempotency & observability:** Add job deduplication keys, structured logging, and OpenTelemetry traces across API → queue → worker → DB.
