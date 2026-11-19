"""Deterministic evaluation of CT-10, registry and consent evidence."""

import re
from datetime import date, timedelta

from .models import (
    Case, ConsentDocument, ConsentPack, CT10, Evaluation, Finding,
    Outcome, Pathway, TrialEvidence, WorkingCalendar,
)

RULESET_VERSION = "ndct-2019-gsr46e-2026-v2"
# The 6 March implementation circular overlaps the Gazette's 45-day
# commencement window. Route 6–7 March filings to review.
TRANSITION_START = date(2026, 3, 6)
AMENDED_FROM = date(2026, 3, 8)
NDCT = "NDCT Rules 2019, G.S.R. 227(E)"
CT10_SOURCE = f"{NDCT}, rules 52–54; G.S.R. 46(E); CDSCO circular IT/MISC/001/2026"
CTRI_SOURCE = f"{NDCT}, rule 25(v)–(vi); CTRI FAQ"
CONSENT_SOURCE = f"{NDCT}, Third Schedule §2 and Table 3; ICMR 2017 §5"

ESSENTIAL_ELEMENTS = frozenset({
    "research_purpose", "participation_duration", "procedures", "risks",
    "expected_benefits", "alternatives", "confidentiality_and_access",
    "free_medical_management", "injury_or_death_compensation", "contacts",
    "participant_responsibilities", "voluntary_withdrawal_without_penalty",
    "possible_lack_of_therapeutic_effect",
})
CONDITIONAL_ELEMENTS = {
    "randomized": "randomization_and_treatment_schedule",
    "placebo_controlled": "placebo_lacks_therapeutic_effect",
    "prorated_payment": "prorated_payment",
}


def _finding(rule_id: str, outcome: Outcome, source: str, message: str,
             *references: str | None) -> Finding:
    return Finding(rule_id=rule_id, outcome=outcome, source_ref=source,
                   message=message, evidence_refs=tuple(ref for ref in references if ref))


def _working_deadline(calendar: WorkingCalendar | None, start: date, days: int) -> date | None:
    if calendar is None or not calendar.valid_from <= start <= calendar.valid_through:
        return None
    current = start
    while days and current < calendar.valid_through:
        current += timedelta(days=1)
        if current.weekday() in calendar.working_weekdays and current not in calendar.holidays:
            days -= 1
    return None if days else current


def _standard_validity_elapsed(issued: date, started: date) -> bool:
    if started.year - issued.year < 3:
        return False
    day = 28 if (issued.month, issued.day) == (2, 29) else issued.day
    return started >= date(issued.year + 3, issued.month, day)


def _timeline(case, findings, rule_id, start, response, response_type, days):
    deadline = _working_deadline(case.calendar, start.date, days)
    refs = (start.reference, case.calendar.reference if case.calendar else None,
            response.reference if response else None)
    if deadline is None:
        outcome, message = "review", "Supply a working-day calendar covering the full response period."
    elif response is not None:
        if not start.date <= response.date <= case.as_of or response_type is None:
            outcome, message = "review", "Verify the response date and type."
        elif response.date > deadline:
            outcome, message = "fail", f"The authority response came after {deadline}."
        else:
            outcome, message = "pass", f"The {response_type} response was recorded by {deadline}."
    elif case.as_of <= deadline:
        outcome, message = "review", f"Authority response pending. The deadline is {deadline}."
    else:
        outcome, message = "review", (
            f"No response evidence by {deadline}. Verify the communication history and "
            "any applicable deemed approval and CT-11A filing under G.S.R. 778(E)."
        )
    if start.date < TRANSITION_START <= (response.date if response else min(case.as_of, deadline or case.as_of)):
        outcome, message = "review", "Confirm the applicable timeline for a filing spanning commencement."
        deadline = None
    findings.append(_finding(rule_id, outcome, CT10_SOURCE, message, *refs))
    return deadline


def _manufacture_check(case: Case, ct10: CT10, route: Pathway, findings: list[Finding]):
    if ct10.manufacture_started is None:
        return
    start = ct10.manufacture_started
    if (route == "prior_intimation" and ct10.submitted_as == route
            and ct10.authority_response is None and ct10.response_type is None):
        document = ct10.acknowledgement
    elif route == "prior_permission" and ct10.submitted_as == route:
        document = None
        if ct10.response_type == "ct11":
            document = ct10.authority_response
        elif (
            ct10.response_type == "deficiency_notice"
            and ct10.resubmission_decision_type == "ct11"
            and ct10.authority_response and ct10.resubmission_received and ct10.resubmission_decision
            and ct10.received.date <= ct10.authority_response.date
            <= ct10.resubmission_received.date <= ct10.resubmission_decision.date
        ):
            document = ct10.resubmission_decision
    else:
        document = None
    if start.date > case.as_of or document is None or not ct10.received.date <= document.date <= case.as_of:
        outcome, message = "review", "Verify the manufacture date and evidence of the applicable authorization."
    elif document.date > start.date:
        outcome, message = "fail", "Manufacture began before the evidenced authorization."
    elif document.date == start.date:
        outcome, message = "review", "Verify that authorization preceded manufacture on the same day."
    elif _standard_validity_elapsed(document.date, start.date):
        outcome, message = "review", "Verify Rule 54 validity or extension at the recorded manufacture start."
    else:
        outcome, message = "pass", "The authorization predates the recorded manufacture start."
    findings.append(_finding("ct10.manufacture_start", outcome, CT10_SOURCE, message,
                             start.reference, document.reference if document else None))


def _ct10(case: Case, ct10: CT10, findings: list[Finding]):
    receipt = ct10.received
    if receipt is None or receipt.date > case.as_of or ct10.purpose is None:
        finding = _finding("ct10.pathway", "review", CT10_SOURCE,
                           "Supply a CT-10 receipt date and manufacture purpose as of the evaluation date.",
                           receipt.reference if receipt else None)
        findings.append(finding)
        return "undetermined", None, None, None

    amended = receipt.date >= AMENDED_FROM
    testing = ct10.purpose in {"analytical_testing", "nonclinical_testing"}
    in_transition = TRANSITION_START <= receipt.date < AMENDED_FROM
    if in_transition or (amended and testing and not ct10.drug_classes):
        findings.append(_finding("ct10.pathway", "review", CT10_SOURCE,
                                 "Verify the applicable commencement date." if in_transition else
                                 "Supply the drug classification to assess prior-intimation eligibility.",
                                 receipt.reference))
        return "undetermined", None, None, None

    route = "prior_intimation" if amended and testing and ct10.drug_classes == {"other"} else "prior_permission"
    outcome = "review" if ct10.submitted_as is None else "pass" if ct10.submitted_as == route else "fail"
    findings.append(_finding("ct10.pathway", outcome, CT10_SOURCE,
                             f"Required pathway: {route}. Documented filing: {ct10.submitted_as or 'unknown'}.",
                             receipt.reference))
    if route == "prior_intimation":
        ack = ct10.acknowledgement
        conflicting_response = ct10.authority_response is not None or ct10.response_type is not None
        current = (ct10.submitted_as == route and ack is not None
                   and receipt.date <= ack.date <= case.as_of and not conflicting_response)
        findings.append(_finding(
            "ct10.acknowledgement", "pass" if current else "review", CT10_SOURCE,
            "NSWS submission acknowledgement recorded." if current else
            "Reconcile the authority response with the prior-intimation filing." if conflicting_response else
            "Verify the matching NSWS submission acknowledgement before manufacture.",
            receipt.reference, ack.reference if ack else None,
        ))
        _manufacture_check(case, ct10, route, findings)
        return route, None, None, None

    days = 45 if amended else 90
    due = _timeline(case, findings, "ct10.response_timeline", receipt,
                    ct10.authority_response, ct10.response_type, days)
    resubmission_due = None
    if ct10.response_type == "deficiency_notice":
        notice = ct10.authority_response
        resubmission = ct10.resubmission_received
        if (notice and resubmission and receipt.date <= notice.date <= resubmission.date <= case.as_of
                and not receipt.date < TRANSITION_START <= resubmission.date):
            resubmission_due = _timeline(case, findings, "ct10.resubmission_timeline", resubmission,
                                         ct10.resubmission_decision, ct10.resubmission_decision_type, days)
        else:
            findings.append(_finding("ct10.resubmission_timeline", "review", CT10_SOURCE,
                                     "Verify the deficiency notice, resubmission receipt and applicable regime.",
                                     notice.reference if notice else None,
                                     resubmission.reference if resubmission else None))
    if ct10.response_type == "rejection":
        rejection = ct10.authority_response
        rejection_start = receipt
    elif ct10.response_type == "deficiency_notice" and ct10.resubmission_decision_type == "rejection":
        rejection = ct10.resubmission_decision
        notice, resubmission = ct10.authority_response, ct10.resubmission_received
        rejection_start = resubmission if notice and resubmission and receipt.date <= notice.date <= resubmission.date else None
    else:
        rejection = rejection_start = None
    if rejection and rejection_start and receipt.date <= rejection_start.date <= rejection.date <= case.as_of:
        findings.append(_finding("ct10.permission_rejected", "fail", CT10_SOURCE,
                                 "The recorded authority decision rejected the CT-10 permission application.",
                                 rejection.reference))
    _manufacture_check(case, ct10, route, findings)
    return route, days, due, resubmission_due


def _normalized(value):
    if isinstance(value, frozenset):
        return frozenset(_normalized(item) for item in value)
    return " ".join(value.split()).casefold()


def _registry(case: Case, trial: TrialEvidence, findings: list[Finding]):
    protocol, registry = trial.protocol, trial.registry
    valid_ctri_id = False
    if protocol is None or registry is None:
        findings.append(_finding("ctri.records", "review", CTRI_SOURCE,
                                 "Supply the approved protocol and a local CTRI record."))
    if registry is not None:
        ctri_id = registry.ctri_id
        valid_ctri_id = bool(ctri_id and re.fullmatch(
            r"CTRI/[0-9]{4}/(?:0[1-9]|1[0-2])/[0-9]{6}", ctri_id.upper()
        ))
        outcome = "review" if ctri_id is None else "pass" if valid_ctri_id else "fail"
        findings.append(_finding("ctri.identifier", outcome, CTRI_SOURCE,
                                 "Verify the final CTRI registration identifier.", registry.reference))

    fields = ("protocol_id", "protocol_version", "sponsor", "design", "india_sites")
    for document in ((registry,) if registry else ()) + trial.supporting_documents:
        for field in fields + ("ctri_id",):
            baseline = registry if field == "ctri_id" else protocol
            if baseline is None or baseline is document:
                continue
            expected, actual = getattr(baseline, field), getattr(document, field)
            if expected is None and actual is None and field in {"protocol_version", "ctri_id"}:
                continue
            outcome = "review" if expected is None or actual is None else (
                "pass" if _normalized(expected) == _normalized(actual) else "fail"
            )
            findings.append(_finding(f"ctri.consistency.{field}", outcome, CTRI_SOURCE,
                                     f"Compare {field} with the reference record.",
                                     baseline.reference, document.reference))
    if protocol and registry and protocol.ctri_id:
        outcome = "review" if registry.ctri_id is None else (
            "pass" if _normalized(protocol.ctri_id) == _normalized(registry.ctri_id) else "fail"
        )
        findings.append(_finding("ctri.consistency.ctri_id", outcome, CTRI_SOURCE,
                                 "Compare the CTRI identifier stated in the protocol.",
                                 protocol.reference, registry.reference))

    first = trial.first_enrolment
    registered = registry.registered_on if registry else None
    registry_first = registry.actual_first_enrolment if registry else None
    refs = (registry.reference if registry else None, first.reference if first else None)
    if first and registry_first:
        comparison = "review" if max(first.date, registry_first) > case.as_of else (
            "pass" if first.date == registry_first else "fail"
        )
        findings.append(_finding("ctri.consistency.first_enrolment",
                                 comparison,
                                 CTRI_SOURCE, "Compare the actual first enrolment dates.", *refs))

    dates = [day for day in (registry_first, first.date if first else None) if day is not None]
    if not valid_ctri_id or registered is None or registered > case.as_of:
        outcome, message = "review", "Verify the final CTRI identifier and registration date."
    elif any(registered > day and day <= case.as_of for day in dates):
        outcome, message = "fail", "Recorded enrolment preceded CTRI registration."
    elif any(day > case.as_of for day in dates):
        outcome, message = "review", "Verify dated registration and enrolment evidence as of the evaluation date."
    elif registered in dates:
        outcome, message = "review", "Verify the sequence within the same calendar day."
    elif dates and trial.enrolment_started is False:
        outcome, message = "review", "Actual enrolment dates conflict with the reported enrolment status."
    elif dates or trial.enrolment_started is False:
        outcome, message = "pass", "Registration precedes dated enrolment or enrolment is reported as not started."
    else:
        outcome, message = "review", "Supply actual first enrolment evidence or confirm enrolment has not started."
    findings.append(_finding("ctri.prospective_registration", outcome, CTRI_SOURCE, message, *refs))


def _consent_document(case: Case, pack: ConsentPack, document: ConsentDocument | None,
                      kind: str, findings: list[Finding]):
    refs = (document.reference, document.approval.reference if document.approval else None) if document else ()
    if document is None or document.readable is not True:
        outcome, message = "review", "Supply a readable copy."
    elif not document.version or not document.ec_approved_version or not document.approval:
        outcome, message = "review", "Supply the document version and dated Ethics Committee approval."
    elif document.approval.date > case.as_of or (pack.first_used_on and pack.first_used_on > case.as_of):
        outcome, message = "review", "Verify document use and approval dates as of the evaluation date."
    elif document.version != document.ec_approved_version:
        outcome, message = "fail", "The supplied version differs from the Ethics Committee approved version."
    elif pack.first_used_on and document.approval.date > pack.first_used_on:
        outcome, message = "fail", "Ethics Committee approval postdates first use."
    elif pack.first_used_on == document.approval.date:
        outcome, message = "review", "Verify that Ethics Committee approval preceded use on the same day."
    else:
        outcome, message = "pass", "The supplied version matches the documented Ethics Committee approval."
    findings.append(_finding(f"consent.{kind}", outcome, CONSENT_SOURCE,
                             f"{pack.site} / {pack.language}. {message}", *refs))


def _consent_pack(case: Case, trial: TrialEvidence, pack: ConsentPack, findings: list[Finding]):
    label = f"{pack.site} / {pack.language}"
    docs = (pack.information_sheet, pack.written_form)
    refs = tuple(doc.reference for doc in docs if doc)
    protocol = trial.protocol
    if not protocol or not all((protocol.protocol_id, protocol.protocol_version,
                                pack.protocol_id, pack.protocol_version)):
        outcome = "review"
    elif (protocol.protocol_id, protocol.protocol_version) == (pack.protocol_id, pack.protocol_version):
        outcome = "pass"
    else:
        outcome = "fail"
    findings.append(_finding("consent.protocol_version", outcome, CONSENT_SOURCE,
                             f"{label}. Compare the pack with the approved protocol ID and version.",
                             protocol.reference if protocol else None, *refs))

    for document, kind in zip(docs, ("information_sheet", "written_form")):
        _consent_document(case, pack, document, kind, findings)

    review = pack.language_review
    outcome = "review"
    readable_pack = all(doc is not None and doc.readable is True for doc in docs)
    if readable_pack and review and review.date <= case.as_of and pack.language_understandable is not None:
        outcome = "pass" if pack.language_understandable else "fail"
    findings.append(_finding("consent.understandable_language", outcome, CONSENT_SOURCE,
                             f"{label}. Verify documented human review of language and translation.",
                             *refs, review.reference if review else None))

    required = ESSENTIAL_ELEMENTS | trial.additional_required_elements
    required |= {element for field, element in CONDITIONAL_ELEMENTS.items() if getattr(trial, field) is True}
    unknown = [field for field in CONDITIONAL_ELEMENTS if getattr(trial, field) is None]
    if unknown:
        findings.append(_finding("consent.checklist_applicability", "review", CONSENT_SOURCE,
                                 f"{label}. Verify applicability for {', '.join(unknown)}.", *refs))
    for element in sorted(required):
        evidence = pack.elements.get(element) if pack.elements is not None else None
        if pack.elements is None or not readable_pack:
            outcome = "review"
        else:
            outcome = "pass" if evidence else "fail"
        findings.append(_finding(f"consent.element.{element}", outcome, CONSENT_SOURCE,
                                 f"{label}. Check the consent evidence for {element}.", *refs, evidence))


def _consent(case: Case, trial: TrialEvidence, findings: list[Finding]):
    languages_by_site = trial.required_languages or {}
    protocol_sites = trial.protocol.india_sites if trial.protocol else None
    if not languages_by_site or not protocol_sites:
        findings.append(_finding("consent.language_requirements", "review", CONSENT_SOURCE,
                                 "Supply protocol sites and participant language requirements for each site."))
    for site in sorted(set(languages_by_site) | (protocol_sites or set())):
        if protocol_sites and site not in protocol_sites:
            findings.append(_finding("consent.language_requirements", "review", CONSENT_SOURCE,
                                     f"{site}. Reconcile the language requirements with the approved sites.",
                                     trial.protocol.reference))
            continue
        languages = languages_by_site.get(site)
        if not languages:
            findings.append(_finding("consent.language_requirements", "review", CONSENT_SOURCE,
                                     f"{site}. Supply participant language requirements."))
            continue
        for language in sorted({_normalized(tag) for tag in languages}):
            packs = [pack for pack in trial.consent_packs
                     if pack.site == site and _normalized(pack.language) == language]
            if len(packs) != 1:
                findings.append(_finding("consent.language_pack", "review", CONSENT_SOURCE,
                                         f"{site} / {language}. Identify one current consent pack."))
            else:
                _consent_pack(case, trial, packs[0], findings)


def evaluate(case: Case) -> Evaluation:
    """Evaluate supplied evidence groups as of the case date.

    References identify offline records already linked to the case. Language and
    checklist findings use documented human assessments of the consent versions.
    """
    findings: list[Finding] = []
    pathway = working_days = response_due = resubmission_due = None
    if case.ct10 is not None:
        pathway, working_days, response_due, resubmission_due = _ct10(case, case.ct10, findings)
    if case.trial is not None:
        _registry(case, case.trial, findings)
        _consent(case, case.trial, findings)
    if not findings:
        findings.append(_finding("vaidyasetu.evidence", "review", NDCT,
                                 "Supply CT-10 or clinical trial evidence."))
    return Evaluation(case_ref=case.case_ref, as_of=case.as_of, ruleset_version=RULESET_VERSION,
                      pathway=pathway, working_days=working_days, response_due_on=response_due,
                      resubmission_due_on=resubmission_due, findings=tuple(findings))
