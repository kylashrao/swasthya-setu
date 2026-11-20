"""FastAPI entry point for local and Vercel use."""

import json
import sqlite3
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.audit_workflow import DATA, audit_database, record_audit
from core.vernacular_engine import LANGUAGES, VerificationRequest, sample_phrases, verify
from modules import ayushman_sarathi, vaidyasetu
from modules.vaidyasetu.models import Record
from modules.vaidyasetu.sec_simulator import SimulationRequest, simulate

app = FastAPI(title="SwasthyaSetu", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Omit submitted values from validation errors.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": issue["loc"], "type": issue["type"]} for issue in exc.errors()
    ]})


class ClaimRequest(Record):
    admission: ayushman_sarathi.Admission
    schedule: ayushman_sarathi.Schedule


def _audit(module, result, reference):
    try:
        receipt = record_audit(audit_database(), module, result, reference)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "The local audit database is unavailable.") from exc
    return {"evaluation": result, "receipt": receipt}


@app.post("/api/vaidyasetu")
def clinical(case: vaidyasetu.Case):
    result = vaidyasetu.evaluate(case)
    return _audit("vaidyasetu", result, result.case_ref)


@app.post("/api/ayushman-sarathi")
def claim(request: ClaimRequest):
    result = ayushman_sarathi.evaluate(request.admission, request.schedule)
    return _audit("ayushman_sarathi", result, result.admission_ref)


@app.post("/api/vernacular")
def vernacular(request: VerificationRequest):
    try:
        return verify(request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/sec")
def sec(request: SimulationRequest):
    return simulate(request)


@app.get("/api/samples/{module}")
def samples(module: Literal["vaidyasetu", "ayushman-sarathi", "vernacular"]):
    if module == "vernacular":
        source = {key: row["en"] for key, row in sample_phrases().items()}
        return {name: {"language": code, "source": source} for code, name in LANGUAGES.items()}
    data = json.loads((DATA / "samples" / (module.replace("-", "_") + ".json")).read_text(encoding="utf-8"))
    if module == "vaidyasetu":
        return {item["case_ref"]: item for item in data}
    return {key: {"admission": admission, "schedule": data["schedule"]}
            for key, admission in data["scenarios"].items()}
