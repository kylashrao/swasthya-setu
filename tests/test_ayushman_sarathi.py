import json
from pathlib import Path

import pytest

from modules.ayushman_sarathi import Admission, Schedule, evaluate

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples" / "ayushman_sarathi.json"


@pytest.fixture
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def run(sample, scenario="passing_claim"):
    return evaluate(
        Admission.model_validate(sample["scenarios"][scenario]),
        Schedule.model_validate(sample["schedule"]),
    )


def has_finding(result, rule, outcome, message="", line=None):
    return any(finding.rule_id == rule and finding.outcome == outcome
               and message in finding.message and (line is None or finding.line_ref == line)
               for finding in result.findings)


@pytest.mark.parametrize("scenario", ["passing_preauthorization", "passing_claim"])
def test_synthetic_passes_rank_by_tariff_and_accept_readable_images(sample, scenario):
    result = run(sample, scenario)
    assert [(line.package_code, line.basis_points, line.expected_paise) for line in result.line_rates] == [
        ("SYN-GS01", 10_000, 2_300_000),
        ("SYN-GS02", 5_000, 800_000),
    ]
    assert result.expected_total_paise == 3_100_000
    assert all(finding.outcome == "pass" for finding in result.findings)
    assert all(finding.source_ref and finding.evidence_refs for finding in result.findings)
    sample["scenarios"][scenario]["procedures"].reverse()
    assert result.model_dump_json() == run(sample, scenario).model_dump_json()


def test_failed_claim_reports_mapping_amount_and_attachment_issues(sample):
    result = run(sample, "failing_claim")
    assert has_finding(result, "hbp.mapping", "fail", line="line-02")
    assert has_finding(result, "claim.line_amount", "fail", line="line-02")
    assert has_finding(result, "claim.total_amount", "fail")
    assert has_finding(result, "claim.preauthorization", "review", line="line-02")
    assert has_finding(result, "preop.attachment", "review", "required text", "line-01")
    assert has_finding(result, "preop.attachment", "review", "admission linkage", "line-02")


@pytest.mark.parametrize("field, value", [
    ("sha_code", "GJ"), ("tariff_profile", "urban"), ("tariff_date", "2027-01-01"),
])
def test_wrong_or_outdated_schedule_cannot_produce_tariff(sample, field, value):
    sample["scenarios"]["passing_claim"][field] = value
    result = run(sample)
    assert result.expected_total_paise is None
    assert has_finding(result, "hbp.schedule", "review")


@pytest.mark.parametrize("ambiguous", [False, True])
def test_unsupported_and_ambiguous_procedures_do_not_price_partial_claim(sample, ambiguous):
    if ambiguous:
        sample["schedule"]["packages"][1]["procedure_keys"].append("open inguinal hernia repair")
    else:
        sample["scenarios"]["passing_claim"]["procedures"][1]["procedure_key"] = "unlisted procedure"
    result = run(sample)
    assert has_finding(result, "hbp.mapping", "review", line="line-01")
    assert result.expected_total_paise is None
    assert result.line_rates == ()


def test_schedule_combination_override_and_paise_rounding(sample):
    schedule = sample["schedule"]
    schedule["packages"][1]["tariff_paise"] = 1_600_002
    schedule["overrides"] = [{
        "package_codes": ["SYN-GS01", "SYN-GS02"], "rank_basis_points": [10_000, 7_500],
        "source_ref": "Synthetic combination override",
    }]
    result = run(sample)
    assert result.line_rates[1].expected_paise == 1_200_002
    assert result.line_rates[1].source_ref == "Synthetic combination override"

    schedule["rounding"] = "down"
    schedule["rounding_unit_paise"] = 100
    assert run(sample).line_rates[1].expected_paise == 1_200_000


def test_third_rank_uses_schedule_and_undefined_rank_needs_review(sample):
    sample["schedule"]["packages"].append({
        "code": "SYN-GS03", "procedure_keys": ["third documented procedure"], "kind": "surgical",
        "tariff_paise": 1_000_000, "source_ref": "Synthetic tariff", "preop_checklist": [],
        "preauthorization_required": False,
    })
    claim = sample["scenarios"]["passing_claim"]
    claim["procedures"].append({
        "line_ref": "line-03", "source_ref": "synthetic-plan.pdf#line-03",
        "procedure_key": "third documented procedure", "submitted_code": "SYN-GS03",
        "submitted_paise": 250_000,
    })
    assert run(sample).line_rates[2].expected_paise == 250_000

    sample["schedule"]["surgical_rank_basis_points"].pop()
    assert has_finding(run(sample), "hbp.pricing", "review", "every required rank")


def test_session_schedule_ranks_each_session_independently(sample):
    sample["schedule"]["surgical_grouping"] = "ot_session"
    line = sample["scenarios"]["passing_claim"]["procedures"][0]
    line["ot_session_ref"] = "ot-02"
    result = run(sample)
    assert [rate.rank for rate in result.line_rates] == [1, 1]
    assert result.expected_total_paise == 3_900_000

    del line["ot_session_ref"]
    assert has_finding(run(sample), "hbp.pricing", "review", "OT session")


@pytest.mark.parametrize("change, message", [
    ({"line_ref": "another-line"}, "linked attachment is missing"),
    ({"readable": False}, "readability"),
    ({"uploaded_at": "2026-05-12T09:16:00+05:30"}, "after pre-authorization"),
    ({"recorded_at": "2026-05-13T10:00:00+05:30",
      "uploaded_at": "2026-05-13T10:01:00+05:30"}, "after pre-authorization"),
])
def test_mandatory_attachment_failures_route_to_review(sample, change, message):
    sample["scenarios"]["passing_claim"]["attachments"][2].update(change)
    result = run(sample)
    assert has_finding(result, "preop.attachment", "review", message, "line-02")


def test_preauth_upload_alone_cannot_make_postoperative_record_valid(sample):
    rule = sample["schedule"]["packages"][1]["preop_checklist"][1]
    rule["deadline"] = "preoperative"
    attachment = sample["scenarios"]["passing_claim"]["attachments"][2]
    attachment.update(recorded_at="2026-05-13T10:01:00+05:30",
                      uploaded_at="2026-05-13T10:02:00+05:30")
    assert has_finding(run(sample), "preop.attachment", "review", "before surgery", "line-02")


def test_claim_approval_cannot_predate_submission(sample):
    sample["scenarios"]["passing_claim"]["authorizations"][0]["approved_at"] = "2026-05-12T08:00:00+05:30"
    assert has_finding(run(sample), "claim.preauthorization", "review", "sequence", "line-01")


def test_future_tariff_date_cannot_be_used_as_of_earlier_audit(sample):
    sample["scenarios"]["passing_claim"]["tariff_date"] = "2026-06-01"
    result = run(sample)
    assert result.expected_total_paise is None
    assert has_finding(result, "hbp.schedule", "review")


def test_equal_tariffs_across_different_ranks_require_review(sample):
    first, second = sample["schedule"]["packages"]
    second["tariff_paise"] = first["tariff_paise"]
    result = run(sample)
    assert has_finding(result, "hbp.pricing", "review", "tie-breaking")
    assert not result.line_rates


def test_conflicting_attachment_reference_is_rejected(sample):
    from pydantic import ValidationError

    claim = sample["scenarios"]["passing_claim"]
    claim["attachments"].append({**claim["attachments"][0], "readable": False})
    with pytest.raises(ValidationError, match="conflicting evidence"):
        run(sample)


def test_string_readability_is_not_verified_evidence(sample):
    from pydantic import ValidationError

    sample["scenarios"]["passing_claim"]["attachments"][0]["readable"] = "yes"
    with pytest.raises(ValidationError, match="valid boolean"):
        run(sample)


@pytest.mark.parametrize("timestamp", [1778644200, "1778644200", "2026-05-13T10:00:00"])
def test_claim_time_requires_explicit_timestamp_and_timezone(sample, timestamp):
    from pydantic import ValidationError

    sample["scenarios"]["passing_claim"]["as_of"] = timestamp
    with pytest.raises(ValidationError, match="timezone"):
        run(sample)


def test_actual_surgery_time_is_reviewed_without_preauthorization_requirement(sample):
    package = sample["schedule"]["packages"][0]
    package.update(preauthorization_required=False, preop_checklist=[])
    del sample["scenarios"]["passing_claim"]["procedures"][1]["surgery_at"]
    assert has_finding(run(sample), "claim.procedure_time", "review", "actual surgery", "line-01")
