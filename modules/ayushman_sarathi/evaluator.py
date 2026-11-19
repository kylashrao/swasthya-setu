"""Audit one admission against a supplied SHA tariff and checklist."""

from collections import defaultdict
from datetime import timedelta, timezone
from unicodedata import normalize

from .models import (
    Admission, Attachment, AttachmentRule, Evaluation, Finding, LineRate,
    Outcome, Package, Procedure, Schedule,
)

RULESET_VERSION = "pmjay-hbp-v2"
NHA_GUIDANCE = "NHA HBP 2.2 manual, §§4.1–4.2"
INDIA_TIME = timezone(timedelta(hours=5, minutes=30))
MappedLine = tuple[Procedure, Package]


def _finding(rule_id: str, outcome: Outcome, source: str, message: str,
             *refs: str | None, line: Procedure | None = None) -> Finding:
    return Finding(rule_id=rule_id, outcome=outcome, source_ref=source, message=message,
                   evidence_refs=tuple(dict.fromkeys(ref for ref in refs if ref)),
                   line_ref=line.line_ref if line else None)


def _key(value: str) -> str:
    return " ".join(normalize("NFKC", value).split()).casefold()


def _map(line: Procedure, schedule: Schedule) -> tuple[Package | None, Finding]:
    key = _key(line.procedure_key) if line.procedure_key else None
    candidates = [
        package for package in schedule.packages
        if key in {_key(alias) for alias in package.procedure_keys}
    ]
    if len(candidates) != 1:
        codes = ", ".join(sorted(package.code for package in candidates))
        message = f"Procedure matches multiple HBP codes: {codes}." if candidates else (
            "Supply a documented procedure key supported by the applicable schedule."
        )
        return None, _finding("hbp.mapping", "review", schedule.source_ref, message,
                              line.source_ref, line=line)
    package = candidates[0]
    if line.submitted_code is None:
        outcome, message = "review", f"Supply the submitted code for mapped package {package.code}."
    elif line.submitted_code != package.code:
        outcome, message = "fail", f"Submitted code {line.submitted_code} differs from {package.code}."
    else:
        outcome, message = "pass", f"Documented procedure maps to {package.code}."
    return package, _finding("hbp.mapping", outcome, package.source_ref, message,
                             line.source_ref, line=line)


def _attachment_issue(admission: Admission, line: Procedure, rule: AttachmentRule,
                      attachment: Attachment) -> str | None:
    if attachment.admission_ref != admission.admission_ref:
        return "admission linkage is missing or mismatched"
    if attachment.readable is not True:
        return "readability is unverified"
    if rule.text_required and attachment.has_extractable_text is not True:
        return "required text is missing or unverified"
    recorded, uploaded = attachment.recorded_at, attachment.uploaded_at
    if recorded is None or recorded > admission.as_of:
        return "recording time is missing or outside the audit period"
    if uploaded and not recorded <= uploaded <= admission.as_of:
        return "upload chronology is inconsistent"
    if rule.deadline in {"preauthorization", "both"}:
        submitted = admission.preauthorization_submitted_at
        if submitted is None or submitted > admission.as_of or uploaded is None:
            return "pre-authorization submission or upload time is unverified"
        if uploaded > submitted:
            return "upload occurred after pre-authorization submission"
    if rule.deadline in {"preoperative", "both"}:
        if line.surgery_at is None or (admission.stage == "claim" and line.surgery_at > admission.as_of):
            return "surgery time is unverified"
        if recorded >= line.surgery_at:
            return "attachment was not recorded before surgery"
        if rule.deadline == "both" and uploaded >= line.surgery_at:
            return "attachment was not uploaded before surgery"
    return None


def _attachments(admission: Admission, line: Procedure, package: Package) -> list[Finding]:
    findings = []
    for rule in package.preop_checklist:
        candidates = sorted(
            (attachment for attachment in admission.attachments
             if attachment.kind == rule.kind and attachment.line_ref ==
             (line.line_ref if rule.scope == "procedure" else None)),
            key=lambda item: item.reference,
        )
        checked = [(item, _attachment_issue(admission, line, rule, item)) for item in candidates]
        valid = [item.reference for item, issue in checked if issue is None]
        if valid:
            outcome, message = "pass", f"Verified mandatory {rule.kind} evidence."
            refs = valid
        else:
            issues = sorted({issue for _, issue in checked if issue is not None})
            detail = "; ".join(issues) if issues else "linked attachment is missing"
            outcome, message = "review", f"Mandatory {rule.kind}: {detail}."
            refs = [item.reference for item, _ in checked]
        findings.append(_finding("preop.attachment", outcome, package.source_ref, message,
                                 line.source_ref, *refs, line=line))
    return findings


def _authorization(admission: Admission, line: Procedure, package: Package) -> Finding:
    candidates = sorted(
        (item for item in admission.authorizations if item.line_ref == line.line_ref),
        key=lambda item: item.reference,
    )
    matching = [item for item in candidates if item.admission_ref == admission.admission_ref
                and item.package_code == package.code and item.approved_at <= admission.as_of]
    submitted = admission.preauthorization_submitted_at
    chronological = [item for item in matching if submitted and submitted <= item.approved_at]
    if not matching:
        outcome, message = "review", "Supply approval linked to this admission, line and mapped package."
    elif not chronological:
        outcome, message = "review", "Verify the sequence of pre-authorization submission and approval."
    elif package.kind == "medical":
        outcome, message = "pass", "Approval matches the admission, line and mapped package."
    elif line.surgery_at is None or line.surgery_at > admission.as_of:
        outcome, message = "review", "Verify actual surgery time to check prior approval."
    elif any(item.approved_at < line.surgery_at for item in chronological):
        outcome, message = "pass", "Matching approval predates surgery."
    elif any(item.approved_at == line.surgery_at for item in chronological):
        outcome, message = "review", "Verify whether approval preceded surgery."
    else:
        outcome, message = "review", "Approval postdates surgery. Check applicable exception evidence."
    return _finding("claim.preauthorization", outcome, package.source_ref, message,
                    line.source_ref, *(item.reference for item in candidates), line=line)


def _amount(tariff: int, basis_points: int, schedule: Schedule) -> int:
    divisor = 10_000 * schedule.rounding_unit_paise
    units, remainder = divmod(tariff * basis_points, divisor)
    if schedule.rounding == "half_up" and 2 * remainder >= divisor:
        units += 1
    return units * schedule.rounding_unit_paise


def _rates(mapped: list[MappedLine], schedule: Schedule) -> list[LineRate] | str:
    if len({package.kind for _, package in mapped}) > 1:
        return "Mixed surgical and medical packages require review under the applicable schedule."
    if mapped[0][1].kind == "medical":
        if len(mapped) > 1:
            return "Multiple medical packages require a separately verified payment rule."
        groups = {"admission": mapped}
    elif schedule.surgical_grouping == "admission":
        groups = {"admission": mapped}
    else:
        if len(mapped) > 1 and any(line.ot_session_ref is None for line, _ in mapped):
            return "Verify the OT session for every procedure before allocating rates."
        groups = defaultdict(list)
        for line, package in mapped:
            groups[line.ot_session_ref or "single"].append((line, package))

    overrides = {override.package_codes: override for override in schedule.overrides}
    rates = []
    for _, group in sorted(groups.items()):
        ranked = sorted(group, key=lambda item: (-item[1].tariff_paise, item[1].code, item[0].line_ref))
        codes = frozenset(package.code for _, package in ranked)
        if len(codes) != len(ranked):
            return "Repeated package codes in one pricing group require review."
        override = overrides.get(codes)
        fractions = override.rank_basis_points if override else schedule.surgical_rank_basis_points
        if ranked[0][1].kind == "medical":
            fractions = (10_000,)
        if len(ranked) > len(fractions):
            return "The applicable schedule does not specify every required rank."
        for index, ((_, first), (_, second)) in enumerate(zip(ranked, ranked[1:])):
            if first.tariff_paise == second.tariff_paise and fractions[index] != fractions[index + 1]:
                return "Equal tariffs cross different ranks. Verify the applicable tie-breaking rule."
        for rank, ((line, package), fraction) in enumerate(zip(ranked, fractions), start=1):
            rates.append(LineRate(line_ref=line.line_ref, package_code=package.code,
                                  rank=rank, tariff_paise=package.tariff_paise,
                                  basis_points=fraction,
                                  expected_paise=_amount(package.tariff_paise, fraction, schedule),
                                  source_ref=override.source_ref if override else schedule.source_ref))
    return rates


def _compare_amount(rule_id: str, submitted: int | None, expected: int, source: str,
                    *refs: str, line: Procedure | None = None) -> Finding:
    if submitted is None:
        outcome, message = "review", f"Supply the submitted amount. Expected {expected} paise."
    elif submitted != expected:
        outcome, message = "fail", f"Submitted {submitted} paise. Expected {expected} paise."
    else:
        outcome, message = "pass", f"Submitted amount matches {expected} paise."
    return _finding(rule_id, outcome, source, message, *refs, line=line)


def _result(admission: Admission, schedule: Schedule | None, findings: list[Finding],
            rates: tuple[LineRate, ...] = (), total: int | None = None) -> Evaluation:
    return Evaluation(
        admission_ref=admission.admission_ref, stage=admission.stage, as_of=admission.as_of,
        ruleset_version=RULESET_VERSION, schedule_version=schedule.version if schedule else None,
        line_rates=rates, expected_total_paise=total, findings=tuple(findings),
    )


def evaluate(admission: Admission, schedule: Schedule | None = None) -> Evaluation:
    """Audit recorded evidence and calculate the expected tariff for one stage.

    The caller supplies the tariff date and SHA profile, plus checklist evidence
    assessed against local records. At pre-authorization, surgery time may be
    planned. At claim review, it represents the actual recorded time.
    """
    if schedule is None or (
        _key(admission.sha_code) != _key(schedule.sha_code)
        or _key(admission.tariff_profile) != _key(schedule.tariff_profile)
        or admission.tariff_date < schedule.effective_from
        or admission.tariff_date > admission.as_of.astimezone(INDIA_TIME).date()
        or (schedule.effective_through and admission.tariff_date > schedule.effective_through)
    ):
        return _result(admission, schedule, [_finding(
            "hbp.schedule", "review", schedule.source_ref if schedule else NHA_GUIDANCE,
            "Supply the schedule covering the SHA, rural tariff profile and tariff date.",
            admission.admission_ref,
        )])

    findings = [_finding("hbp.schedule", "pass", schedule.source_ref,
                         f"Schedule {schedule.version} applies to the supplied tariff profile and date.",
                         admission.admission_ref)]
    if not admission.procedures:
        findings.append(_finding("hbp.mapping", "review", schedule.source_ref,
                                 "Supply the documented procedure lines.", admission.admission_ref))
        return _result(admission, schedule, findings)

    if (admission.stage == "preauthorization" and
            (admission.preauthorization_submitted_at is None
             or admission.preauthorization_submitted_at > admission.as_of)):
        findings.append(_finding("preauthorization.submission", "review", schedule.source_ref,
                                 "Verify the submission time as of the evaluation time.", admission.admission_ref))

    mapped = []
    for line in sorted(admission.procedures, key=lambda item: item.line_ref):
        package, mapping = _map(line, schedule)
        findings.append(mapping)
        if package is None:
            continue
        mapped.append((line, package))
        findings.extend(_attachments(admission, line, package))
        if admission.stage == "claim":
            if package.kind == "surgical" and (line.surgery_at is None or line.surgery_at > admission.as_of):
                findings.append(_finding("claim.procedure_time", "review", package.source_ref,
                                         "Verify the actual surgery time as of the evaluation time.",
                                         line.source_ref, line=line))
            if package.preauthorization_required:
                findings.append(_authorization(admission, line, package))

    pricing = _rates(mapped, schedule) if len(mapped) == len(admission.procedures) else (
        "Resolve all procedure mappings before calculating the admission tariff."
    )
    if isinstance(pricing, str):
        findings.append(_finding("hbp.pricing", "review", schedule.source_ref, pricing,
                                 admission.admission_ref))
        return _result(admission, schedule, findings)

    lines = {line.line_ref: line for line, _ in mapped}
    stage = admission.stage
    for rate in pricing:
        line = lines[rate.line_ref]
        findings.append(_compare_amount(f"{stage}.line_amount", line.submitted_paise,
                                        rate.expected_paise, rate.source_ref, line.source_ref, line=line))
    total = sum(rate.expected_paise for rate in pricing)
    sources = " | ".join(dict.fromkeys(rate.source_ref for rate in pricing))
    findings.append(_compare_amount(f"{stage}.total_amount", admission.submitted_total_paise,
                                    total, sources, admission.admission_ref))
    return _result(admission, schedule, findings, tuple(pricing), total)
