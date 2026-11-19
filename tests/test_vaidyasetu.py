import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from modules.vaidyasetu import Case, evaluate

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples" / "vaidyasetu.json"


@pytest.fixture
def scenarios():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def run(data):
    return evaluate(Case.model_validate(data))


def outcomes(result):
    return {finding.rule_id: finding.outcome for finding in result.findings}


def test_prior_permission_and_trial_fixture_pass(scenarios):
    data = scenarios[0]
    result = run(data)
    assert result.pathway == "prior_permission"
    assert result.working_days == 45
    assert result.response_due_on == date(2026, 5, 13)
    assert all(finding.outcome == "pass" for finding in result.findings)
    assert all(finding.source_ref and finding.evidence_refs for finding in result.findings)
    assert result.model_dump_json() == run(deepcopy(data)).model_dump_json()


def test_failed_fixture_identifies_each_breach(scenarios):
    result = run(scenarios[1])
    assert result.pathway == "prior_permission"
    failures = {key for key, outcome in outcomes(result).items() if outcome == "fail"}
    assert {
        "ct10.pathway", "ct10.response_timeline", "ctri.consistency.protocol_version",
        "ctri.prospective_registration", "consent.written_form",
        "consent.element.injury_or_death_compensation",
    } <= failures


def test_prior_intimation_requires_acknowledgement(scenarios):
    data = scenarios[2]
    result = run(data)
    assert result.pathway == "prior_intimation"
    assert result.working_days is None and result.response_due_on is None
    assert outcomes(result)["ct10.acknowledgement"] == "pass"

    del data["ct10"]["acknowledgement"]
    assert outcomes(run(data))["ct10.acknowledgement"] == "review"


def test_manufacture_before_acknowledgement_fails(scenarios):
    data = scenarios[2]
    data["ct10"]["acknowledgement"]["date"] = "2026-04-09"
    assert outcomes(run(data))["ct10.manufacture_start"] == "fail"


def test_unknown_drug_class_requires_review(scenarios):
    data = scenarios[2]
    del data["ct10"]["drug_classes"]
    result = run(data)
    assert result.pathway == "undetermined"
    assert outcomes(result)["ct10.pathway"] == "review"


@pytest.mark.parametrize("excluded", [
    "sex_hormone", "cytotoxic", "beta_lactam", "live_microorganism_biologic",
    "narcotic", "psychotropic",
])
def test_excluded_classes_require_prior_permission(scenarios, excluded):
    data = scenarios[2]
    data["ct10"]["drug_classes"] = ["other", excluded]
    result = run(data)
    assert result.pathway == "prior_permission"
    assert outcomes(result)["ct10.pathway"] == "fail"


@pytest.mark.parametrize(("received", "days"), [
    ("2025-07-01", 90), ("2026-03-06", None), ("2026-03-09", 45),
])
def test_regime_depends_on_receipt_date(scenarios, received, days):
    data = scenarios[0]
    data["ct10"]["received"]["date"] = received
    assert run(data).working_days == days


@pytest.mark.parametrize(("response_date", "expected"), [
    ("2026-05-13", "pass"), ("2026-05-14", "fail"),
])
def test_deadline_includes_final_working_day(scenarios, response_date, expected):
    data = scenarios[0]
    data["ct10"]["authority_response"]["date"] = response_date
    assert outcomes(run(data))["ct10.response_timeline"] == expected


def test_deficiency_notice_starts_separate_clock_on_resubmission(scenarios):
    data = scenarios[0]
    data["ct10"].update(
        response_type="deficiency_notice",
        resubmission_received={"date": "2026-04-10", "reference": "resubmission"},
        resubmission_decision={"date": "2026-05-29", "reference": "ct11"},
        resubmission_decision_type="ct11",
    )
    result = run(data)
    assert result.resubmission_due_on == date(2026, 6, 16)
    assert outcomes(result)["ct10.resubmission_timeline"] == "pass"


def test_missing_calendar_and_overdue_silence_need_review(scenarios):
    data = scenarios[0]
    del data["calendar"]
    result = run(data)
    assert result.response_due_on is None
    assert outcomes(result)["ct10.response_timeline"] == "review"

    data["calendar"] = scenarios[1]["calendar"]
    del data["ct10"]["authority_response"]
    assert outcomes(run(data))["ct10.response_timeline"] == "review"


def test_missing_language_and_same_day_enrolment_need_review(scenarios):
    data = scenarios[0]
    data["trial"]["registry"]["registered_on"] = "2026-04-20"
    data["trial"]["required_languages"]["Sample District Hospital, Wardha"].append("hi")
    result = run(data)
    assert outcomes(result)["ctri.prospective_registration"] == "review"
    assert any(finding.rule_id == "consent.language_pack" and " / hi." in finding.message
               and finding.outcome == "review" for finding in result.findings)


def test_unreadable_consent_and_unverified_translation_need_review(scenarios):
    data = scenarios[0]
    pack = data["trial"]["consent_packs"][0]
    pack["information_sheet"]["readable"] = False
    del pack["language_review"]
    result = outcomes(run(data))
    assert result["consent.information_sheet"] == "review"
    assert result["consent.understandable_language"] == "review"
    assert result["consent.element.research_purpose"] == "review"


def test_timely_rejection_is_still_a_failed_permission_decision(scenarios):
    data = scenarios[0]
    data["ct10"]["response_type"] = "rejection"
    del data["ct10"]["manufacture_started"]
    result = outcomes(run(data))
    assert result["ct10.response_timeline"] == "pass"
    assert result["ct10.permission_rejected"] == "fail"


def test_prior_intimation_with_conflicting_response_requires_review(scenarios):
    data = scenarios[2]
    data["ct10"].update(response_type="rejection",
                        authority_response={"date": "2026-04-07", "reference": "synthetic-response"})
    result = outcomes(run(data))
    assert result["ct10.acknowledgement"] == "review"
    assert result["ct10.manufacture_start"] == "review"


def test_manufacture_using_old_authorization_requires_validity_review(scenarios):
    data = scenarios[0]
    data["as_of"] = "2029-04-07"
    data["ct10"]["manufacture_started"]["date"] = "2029-04-06"
    assert outcomes(run(data))["ct10.manufacture_start"] == "review"


def test_ct10_commencement_crossing_suppresses_unverified_due_date(scenarios):
    data = scenarios[0]
    data["ct10"]["received"]["date"] = "2026-02-02"
    result = run(data)
    assert outcomes(result)["ct10.response_timeline"] == "review"
    assert result.response_due_on is None


def test_registry_reference_number_cannot_prove_prospective_registration(scenarios):
    data = scenarios[0]
    data["trial"]["registry"]["ctri_id"] = "REF/2026/04/123456"
    result = outcomes(run(data))
    assert result["ctri.identifier"] == "fail"
    assert result["ctri.prospective_registration"] == "review"


def test_future_registry_date_does_not_hide_documented_early_enrolment(scenarios):
    data = scenarios[0]
    data["trial"]["registry"]["actual_first_enrolment"] = "2027-01-01"
    data["trial"]["first_enrolment"]["date"] = "2026-04-13"
    result = outcomes(run(data))
    assert result["ctri.consistency.first_enrolment"] == "review"
    assert result["ctri.prospective_registration"] == "fail"


def test_readability_is_required_to_credit_language_review(scenarios):
    data = scenarios[0]
    data["trial"]["consent_packs"][0]["information_sheet"]["readable"] = False
    assert outcomes(run(data))["consent.understandable_language"] == "review"


@pytest.mark.parametrize("as_of", [0, "0", "2026-05-12T00:00:00"])
def test_ct10_evaluation_date_is_an_explicit_calendar_date(scenarios, as_of):
    from pydantic import ValidationError

    scenarios[0]["as_of"] = as_of
    with pytest.raises(ValidationError, match="calendar date"):
        run(scenarios[0])
