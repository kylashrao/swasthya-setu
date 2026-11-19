"""Persist rule findings and SHA-256 receipts in a local SQLite audit log."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_ref: Reference
    module: Literal["vaidyasetu", "ayushman_sarathi"]
    rule_id: Reference
    ruleset_version: Reference
    source_ref: Reference
    outcome: Literal["pass", "fail", "review"]
    evidence_ref: Reference | None = None


class AuditReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: int
    first_event_id: int
    last_event_id: int
    event_count: int
    recorded_at: str
    sha256: str


def _create_events(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY,
            case_ref TEXT NOT NULL,
            module TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            ruleset_version TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            outcome TEXT NOT NULL,
            evidence_ref TEXT,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _insert_event(connection: sqlite3.Connection, event: AuditEvent) -> int:
    cursor = connection.execute(
        """
        INSERT INTO audit_events (
            case_ref, module, rule_id, ruleset_version, source_ref,
            outcome, evidence_ref
        ) VALUES (
            :case_ref, :module, :rule_id, :ruleset_version, :source_ref,
            :outcome, :evidence_ref
        )
        """,
        event.model_dump(),
    )
    if cursor.rowcount != 1:
        raise sqlite3.IntegrityError("The audit event was not inserted.")
    return cursor.lastrowid


def append_audit_event(database: Path, event: AuditEvent) -> int:
    """Append one finding and return its SQLite row ID."""
    with closing(sqlite3.connect(database)) as connection, connection:
        _create_events(connection)
        return _insert_event(connection, event)


def append_audit_batch(database: Path, events: tuple[AuditEvent, ...]) -> AuditReceipt:
    """Atomically append ordered findings and a SHA-256 receipt for their metadata."""
    if not events:
        raise ValueError("An audit receipt requires at least one event.")
    if len({(event.case_ref, event.module, event.ruleset_version) for event in events}) != 1:
        raise ValueError("An audit receipt must cover a single case, module and ruleset.")
    payload = json.dumps(
        [event.model_dump(mode="json") for event in events],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        _create_events(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_receipts (
                id INTEGER PRIMARY KEY,
                first_event_id INTEGER NOT NULL,
                last_event_id INTEGER NOT NULL,
                event_count INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        event_ids = [_insert_event(connection, event) for event in events]
        first, last = event_ids[0], event_ids[-1]
        cursor = connection.execute(
            """
            INSERT INTO audit_receipts (first_event_id, last_event_id, event_count, sha256)
            VALUES (?, ?, ?, ?)
            """,
            (first, last, len(events), digest),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("The audit receipt was not inserted.")
        receipt_id = cursor.lastrowid
        (recorded_at,) = connection.execute(
            "SELECT recorded_at FROM audit_receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        return AuditReceipt(receipt_id=receipt_id, first_event_id=first, last_event_id=last,
                            event_count=len(events), recorded_at=recorded_at, sha256=digest)
