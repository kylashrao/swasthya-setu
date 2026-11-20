"""Streamlit entry point for the offline SwasthyaSetu demos."""

import json
import sqlite3
from collections import Counter
from pathlib import Path

import streamlit as st
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from core.audit_workflow import audit_database, record_audit
from core.vernacular_engine import DISCLAIMER, LANGUAGES, VerificationRequest, sample_phrases, verify
from modules.vaidyasetu.sec_simulator import SimulationRequest, simulate
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
- The original 70 pytest tests cover the core, both modules, and the Streamlit demo.
- Hindi, Kannada, Tamil, Telugu, and Malayalam ICF comparison and SEC rehearsal are available in both interfaces.

**Planned next phases**

1. Automated CT-04, CT-01, and CTRI drafting with XML and JSON output.
2. Parallel four-worker dossier orchestration.
3. Schedule M CMC checks and risk synthesis from PubMed and ICMR sources.
4. Expand structured ICF and back-translation coverage beyond the current phrasebook. The broader Hindi, Kannada, Tamil, Bengali, and Marathi milestone includes adding Bengali and Marathi.
5. Extend the interactive Subject Expert Committee (SEC) query simulation with more dossier-specific checklists."""
        )



def _show_clinical_tools(case):
    icf, sec = st.tabs(["Vernacular ICF", "SEC Query Simulator"])
    with icf:
        st.caption(DISCLAIMER)
        language = st.selectbox("Consent language", tuple(LANGUAGES), format_func=LANGUAGES.get)
        sample = {key: row["en"] for key, row in sample_phrases().items()}
        source = st.text_area("English clauses (JSON)", json.dumps(sample, ensure_ascii=False, indent=2))
        localized = st.text_area("Localized clauses (optional JSON)")
        reverse = st.text_area("English back-translation (optional JSON)")
        assisted = st.checkbox("Use configured local glossary")
        if st.button("Verify consent clauses"):
            try:
                request = VerificationRequest(language=language, source=json.loads(source),
                                              localized=json.loads(localized) if localized.strip() else None,
                                              back_translation=json.loads(reverse) if reverse.strip() else None,
                                              use_assisted=assisted)
                st.json(verify(request))
            except ValueError as exc:
                st.error(str(exc) if not isinstance(exc, ValidationError) else "Check the consent payload fields.")
    with sec:
        st.caption(f"Selected dossier · {case.case_ref}")
        population = st.text_input("Proposed population (optional)", max_chars=4000)
        request = SimulationRequest(case=case, population=population.strip() or None)
        preview = simulate(request)
        st.caption(preview["notice"])
        responses = {}
        for question in preview["questions"]:
            st.markdown(question["prompt"])
            responses[question["id"]] = {}
            for item in question["checklist"]:
                key = f"{case.case_ref}.{question['id']}.{item['id']}"
                statement = st.text_input(item["requirement"], key=key, max_chars=4000)
                reference = st.text_input("Evidence reference", key=f"{key}.ref", max_chars=4000)
                if statement.strip() and reference.strip():
                    responses[question["id"]][item["id"]] = {
                        "statement": statement, "evidence_ref": reference,
                    }
        if st.button("Evaluate sponsor responses"):
            st.json(simulate(SimulationRequest(case=case, population=request.population,
                                               responses=responses)))

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
    database = audit_database(DATA)
    snapshot = (selected, samples[selected], schedule, database)
    if st.button("Run demo audit", type="primary"):
        st.session_state.pop(state_key, None)
        try:
            result, reference = _evaluate(module, samples[selected], schedule)
            receipt = record_audit(database, module, result, reference)
        except (ValidationError, OSError, sqlite3.Error) as exc:
            st.error(f"Could not complete the demo audit. {exc}")
        else:
            st.session_state[state_key] = (snapshot, result, reference, receipt)

    saved = st.session_state.get(state_key)
    if saved and saved[0] == snapshot:
        _show_result(module, *saved[1:])

    _show_estimator()
    _show_roadmap()
    if module == "vaidyasetu":
        _show_clinical_tools(samples[selected])


if __name__ == "__main__":
    main()
