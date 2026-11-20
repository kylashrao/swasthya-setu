"""Shared persistence for the Streamlit and HTTP audit entry points."""

import json
import os
from pathlib import Path

from .audit_logger import AuditEvent, append_audit_batch

DATA = Path(__file__).resolve().parents[1] / "data"


def audit_database(data=DATA):
    if os.environ.get("VERCEL") == "1":
        return Path("/tmp/audit.sqlite3")
    return Path(os.environ.get("SWASTHYASETU_AUDIT_DB", data / "audit.sqlite3"))


def _audit_evidence(finding) -> str | None:
    line_ref = getattr(finding, "line_ref", None)
    if line_ref is not None:
        return json.dumps({"line_ref": line_ref, "references": finding.evidence_refs}, ensure_ascii=False)
    if finding.evidence_refs:
        return json.dumps(finding.evidence_refs, ensure_ascii=False)
    return None


def record_audit(database, module, result, reference):
    events = tuple(
        AuditEvent(case_ref=reference, module=module, rule_id=finding.rule_id,
                   ruleset_version=result.ruleset_version, outcome=finding.outcome,
                   source_ref=finding.source_ref, evidence_ref=_audit_evidence(finding))
        for finding in result.findings
    )
    return append_audit_batch(database, events)
