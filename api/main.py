from fastapi import FastAPI
from api.routers import jobs
app = FastAPI(
    title="Transaction Processing Pipeline",
    description=(
        "AI-powered backend that ingests dirty transaction CSVs, cleans and flags anomalies, "
        "classifies missing categories via LLM, and produces structured spending summaries."
    ),
    version="1.0.0",
)
app.include_router(jobs.router)
@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}
