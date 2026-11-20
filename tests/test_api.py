import asyncio
import json
import sqlite3
from contextlib import closing

import pytest

from api.index import app
from core.audit_workflow import audit_database


def call(method, path, payload=None):
    """Send a single request to the ASGI app with standard-library tools."""
    messages = []

    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "scheme": "http",
        "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }, receive, send))
    return messages[0]["status"], json.loads(b"".join(message.get("body", b"") for message in messages[1:]))


@pytest.fixture
def database(tmp_path, monkeypatch):
    database = tmp_path / "audit.sqlite3"
    monkeypatch.setenv("SWASTHYASETU_AUDIT_DB", str(database))
    monkeypatch.delenv("VERCEL", raising=False)
    return database


def test_audits_and_receipts(database):
    for index, module in enumerate(("vaidyasetu", "ayushman-sarathi"), start=1):
        status, samples = call("GET", f"/api/samples/{module}")
        assert status == 200
        status, report = call("POST", f"/api/{module}", next(iter(samples.values())))
        assert status == 200
        receipt = report["receipt"]
        assert receipt["receipt_id"] == index
        assert receipt["event_count"] == len(report["evaluation"]["findings"])
        assert len(receipt["sha256"]) == 64
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT sha256 FROM audit_receipts WHERE id=?", (index,)).fetchone() == (receipt["sha256"],)


def test_verification_and_rehearsal(database):
    _, samples = call("GET", "/api/samples/vernacular")
    status, icf = call("POST", "/api/vernacular", samples["Kannada"])
    assert status == 200 and icf["language"] == "kn" and icf["metrics"]["phrase_matches"] == 3
    _, samples = call("GET", "/api/samples/vaidyasetu")
    status, sec = call("POST", "/api/sec", {"case": samples["synthetic-wardha-fail"]})
    assert status == 200 and len(sec["questions"]) == 4
    assert not database.exists()


def test_validation_and_storage_error(database, monkeypatch):
    status, result = call("POST", "/api/vaidyasetu", {"case_ref": "hidden", "as_of": "invalid"})
    assert status == 422 and "invalid" not in json.dumps(result) and "hidden" not in json.dumps(result)
    _, samples = call("GET", "/api/samples/vaidyasetu")
    monkeypatch.setenv("SWASTHYASETU_AUDIT_DB", str(database / "missing" / "audit.sqlite3"))
    assert call("POST", "/api/vaidyasetu", next(iter(samples.values())))[0] == 503


def test_vercel_path_overrides_local_database(database, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert audit_database().as_posix() == "/tmp/audit.sqlite3"
