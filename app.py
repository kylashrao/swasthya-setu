"""Streamlit entry point for the offline SwasthyaSetu demos."""

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

import streamlit as st
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from core.audit_logger import AuditEvent, append_audit_batch
from modules import ayushman_sarathi, vaidyasetu

DATA = Path(__file__).resolve().parent / "data"
VIEWS = {
    "VaidyaSetu": ("vaidyasetu", "CDSCO / NDCT 2026 Clinical Trial & Consent Compliance"),
    "Ayushman-Sarathi": ("ayushman_sarathi", "AB PM-JAY Rural Pre-Auth & Claim Auditor"),
}
CLINICAL_LABELS = {
    "synthetic-wardha-pass": "Clinical trial dossier — passing checks",
    "synthetic-wardha-fail": "Clinical trial dossier — issues found",
    "synthetic-testing-pass": "Analytical testing — acknowledged prior intimation",
}
CLAIM_LABELS = {
    "passing_preauthorization": "Pre-authorization — passing checks",
    "passing_claim": "Claim — passing checks",
    "failing_claim": "Claim — issues found",
}
STATUS = {"pass": "Pass", "fail": "Fail", "review": "Review"}


class ClaimsFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarios: dict[str, ayushman_sarathi.Admission]
    schedule: ayushman_sarathi.Schedule


def _load_samples(module: str):
    path = DATA / "samples" / f"{module}.json"
    data = path.read_text(encoding="utf-8")
    if module == "vaidyasetu":
        cases = TypeAdapter(list[vaidyasetu.Case]).validate_json(data)
        samples = {case.case_ref: case for case in cases}
        if len(samples) != len(cases):
            raise ValueError("Clinical demo case references must be unique.")
        return samples, None, CLINICAL_LABELS
    fixture = ClaimsFixture.model_validate_json(data)
    return fixture.scenarios, fixture.schedule, CLAIM_LABELS


def _evaluate(module, sample, schedule):
    if module == "vaidyasetu":
        result = vaidyasetu.evaluate(sample)
        return result, result.case_ref
    result = ayushman_sarathi.evaluate(sample, schedule)
    return result, result.admission_ref


def _rupees(paise: int) -> str:
    rupees, remainder = divmod(paise, 100)
    return f"₹{rupees:,}.{remainder:02}"


def _audit_evidence(finding) -> str | None:
    line_ref = getattr(finding, "line_ref", None)
    if line_ref is not None:
        return json.dumps({"line_ref": line_ref, "references": finding.evidence_refs}, ensure_ascii=False)
    if finding.evidence_refs:
        return json.dumps(finding.evidence_refs, ensure_ascii=False)
    return None


def _show_result(module, result, reference, receipt):
    st.caption(f"{reference} · Evaluated {result.as_of.isoformat()} · {result.ruleset_version}")
    counts = Counter(finding.outcome for finding in result.findings)
    for (outcome, label), column in zip(STATUS.items(), st.columns(3)):
        column.metric(label, counts[outcome])

    if module == "vaidyasetu" and result.pathway:
        st.markdown(f"**CT-10 pathway** · {result.pathway.replace('_', ' ').title()}")
        if result.response_due_on:
            st.caption(f"Authority response due {result.response_due_on} · {result.working_days} working days")
        if result.resubmission_due_on:
            st.caption(f"Response to resubmission due {result.resubmission_due_on}")
    if module == "ayushman_sarathi" and result.expected_total_paise is not None:
        st.markdown(f"**Expected {result.stage.replace('preauthorization', 'pre-authorization')} total** "
                    f"· {_rupees(result.expected_total_paise)}")
        st.caption(f"Tariff schedule {result.schedule_version}")

    st.subheader("Rule findings")
    for outcome in ("fail", "review", "pass"):
        if not counts[outcome]:
            continue
        with st.expander(f"{STATUS[outcome]} ({counts[outcome]})",
                         expanded=outcome != "pass" or counts["pass"] == len(result.findings)):
            for finding in result.findings:
                if finding.outcome != outcome:
                    continue
                line = getattr(finding, "line_ref", None)
                rule = f"`{finding.rule_id}`" + (f" · {line}" if line else "")
                st.markdown(f"{rule}  \n{finding.message}")
                st.caption(finding.source_ref)
                if finding.evidence_refs:
                    st.caption("Evidence · " + " · ".join(finding.evidence_refs))

    st.subheader("Audit log receipt")
    st.caption(f"Receipt #{receipt.receipt_id} · {receipt.recorded_at} UTC · "
               f"SQLite events {receipt.first_event_id}–{receipt.last_event_id} ({receipt.event_count})")
    st.markdown("**SHA-256 of the ordered finding metadata**")
    st.code(receipt.sha256, language=None)


def _show_estimator():
    st.subheader("Manual Time-Saved Estimator")
    st.caption(
        "Illustrative workflow estimate. Assumes 30 minutes of manual review and "
        "1 minute of deterministic checks per case. Excludes evidence preparation and follow-up review. "
        "No runtimes were measured."
    )
    cases = st.number_input("Cases in batch", min_value=1, max_value=100_000, value=10, step=1)
    manual, checks, difference = st.columns(3)
    manual.metric("Manual review", f"{cases * 30 / 60:,.2f} h")
    checks.metric("Deterministic checks", f"{cases / 60:,.2f} h")
    difference.metric("Estimated time saved", f"{cases * 29 / 60:,.2f} h")


def _show_roadmap():
    with st.expander("Roadmap & Next Milestones"):
        st.markdown(
            """**Shipped today**

- VaidyaSetu checks NDCT 2019 and the January 2026 amendment, CTRI consistency, and vernacular informed consent.
- Ayushman-Sarathi checks AB PM-JAY package mapping, schedule-based rates, and mandatory pre-op attachments.
- Local SQLite audit receipts record a SHA-256 digest of finding metadata.
- 70 pytest tests cover the core, both modules, and the Streamlit demo.

**Planned next phases**

1. Automated CT-04, CT-01, and CTRI drafting with XML and JSON output.
2. Parallel four-worker dossier orchestration.
3. Schedule M CMC checks and risk synthesis from PubMed and ICMR sources.
4. Automated Hindi, Kannada, Tamil, Bengali, and Marathi informed consent form translation and back-translation.
5. Interactive Subject Expert Committee (SEC) query simulation."""
        )


def main():
    st.set_page_config(page_title="SwasthyaSetu", layout="wide")
    view = st.sidebar.radio("Compliance module", tuple(VIEWS))
    module, description = VIEWS[view]
    st.title("SwasthyaSetu")
    st.header(view)
    st.caption(description)

    try:
        samples, schedule, labels = _load_samples(module)
        if not samples:
            raise ValueError("The fixture contains no demo scenarios.")
    except ValidationError as exc:
        issue = exc.errors(include_input=False, include_context=False, include_url=False)[0]
        location = ".".join(map(str, issue["loc"])) or "fixture"
        st.error(f"Invalid local demo data at {location}. {issue['msg']}")
        return
    except (OSError, ValueError) as exc:
        st.error(f"Could not load the local demo samples. {exc}")
        return

    selected = st.selectbox("Load Demo Sample", tuple(samples),
                            format_func=lambda key: labels.get(key, key), key=f"sample_{module}")
    state_key = f"audit_{module}"
    database = Path(os.environ.get("SWASTHYASETU_AUDIT_DB", DATA / "audit.sqlite3"))
    snapshot = (selected, samples[selected], schedule, database)
    if st.button("Run demo audit", type="primary"):
        st.session_state.pop(state_key, None)
        try:
            result, reference = _evaluate(module, samples[selected], schedule)
            events = tuple(
                AuditEvent(case_ref=reference, module=module, rule_id=finding.rule_id,
                           ruleset_version=result.ruleset_version, outcome=finding.outcome,
                           source_ref=finding.source_ref,
                           evidence_ref=_audit_evidence(finding))
                for finding in result.findings
            )
            receipt = append_audit_batch(database, events)
        except (ValidationError, OSError, sqlite3.Error) as exc:
            st.error(f"Could not complete the demo audit. {exc}")
        else:
            st.session_state[state_key] = (snapshot, result, reference, receipt)

    saved = st.session_state.get(state_key)
    if saved and saved[0] == snapshot:
        _show_result(module, *saved[1:])

    _show_estimator()
    _show_roadmap()


if __name__ == "__main__":
    main()
