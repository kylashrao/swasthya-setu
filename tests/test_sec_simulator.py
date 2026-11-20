import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from modules.vaidyasetu.models import Case
from modules.vaidyasetu.sec_simulator import SimulationRequest, simulate


@pytest.fixture
def cases():
    samples = Path(__file__).resolve().parents[1] / "data/samples/vaidyasetu.json"
    return {item["case_ref"]: Case.model_validate(item) for item in json.loads(samples.read_text())}


def test_rehearsal_is_deterministic_and_includes_dossier_findings(cases):
    request = SimulationRequest(case=cases["synthetic-wardha-fail"], population="older adults")
    result = simulate(request)
    assert result == simulate(request)
    questions = {item["id"]: item for item in result["questions"]}
    assert set(questions) == {"sec.ct10", "sec.ctri", "sec.consent", "sec.population"}
    assert any(item["rule_id"] == "ctri.prospective_registration"
               for item in questions["sec.ctri"]["related_findings"])
    assert any("ctri.prospective_registration" in item["requirement"]
               for item in questions["sec.ctri"]["checklist"] if item["id"] == "findings_resolution")
    assert "older adults" in questions["sec.population"]["prompt"]


def test_intimation_route_and_checklist_coverage(cases):
    case = cases["synthetic-testing-pass"]
    question, = simulate(SimulationRequest(case=case))["questions"]
    assert "prior intimation" in question["prompt"]
    assert any("acknowledgement" in item["requirement"] for item in question["checklist"])
    answer = {"statement": "Supporting statement", "evidence_ref": "SYN/appendix"}
    result = simulate(SimulationRequest(case=case, responses={
        "sec.ct10": {"purpose": answer, "irrelevant": answer}, "sec.unknown": {},
    }))
    updated, = result["questions"]
    assert result["unexpected_queries"] == ["sec.unknown"]
    assert updated["coverage"] == "1/4"
    assert updated["status"] == "incomplete"
    assert updated["unexpected_items"] == ["irrelevant"]
    responses = {"sec.ct10": {item["id"]: answer for item in question["checklist"]}}
    assert simulate(SimulationRequest(case=case, responses=responses))["questions"][0]["status"] == "ready_for_review"
    with pytest.raises(ValidationError):
        SimulationRequest(case=case, responses={"sec.ct10": {"purpose": {"statement": " ", "evidence_ref": "x"}}})
