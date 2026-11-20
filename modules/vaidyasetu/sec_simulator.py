"""Evidence checklist rehearsal for a CDSCO Subject Expert Committee discussion."""

from typing import Annotated

from pydantic import Field, StringConstraints

from .evaluator import CONSENT_SOURCE, CT10_SOURCE, CTRI_SOURCE, evaluate
from .models import Case, Record

VERSION = "sec-rehearsal-1.0"
NOTICE = "Training simulation. Checklist coverage reflects submitted statements and references. Independent evidence review is required."
RISK_SOURCE = "NDCT Rules 2019, Third Schedule; ICMR National Ethical Guidelines 2017, §6"
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class EvidenceAnswer(Record):
    statement: Text
    evidence_ref: Text


class SimulationRequest(Record):
    case: Case
    population: Text | None = None
    responses: dict[Text, dict[Text, EvidenceAnswer]] = Field(default_factory=dict)


def simulate(request: SimulationRequest) -> dict:
    result = evaluate(request.case)
    questions = []

    def add(topic, prompt, source, checklist):
        related = [finding.model_dump(mode="json") for finding in result.findings
                   if finding.rule_id.startswith(topic + ".") and finding.outcome != "pass"]
        if related:
            rules = ", ".join(dict.fromkeys(finding["rule_id"] for finding in related))
            checklist["findings_resolution"] = f"Address the dossier findings for {rules} and cite the supporting evidence."
        question_id = f"sec.{topic}"
        submitted = request.responses.get(question_id, {})
        questions.append(dict(
            id=question_id, prompt=prompt, source_ref=source, related_findings=related,
            checklist=[dict(id=key, requirement=label, status="submitted" if key in submitted else "missing")
                       for key, label in checklist.items()],
            coverage=f"{len(checklist.keys() & submitted.keys())}/{len(checklist)}",
            unexpected_items=sorted(submitted.keys() - checklist.keys()),
            status="awaiting_response" if question_id not in request.responses else
                   "ready_for_review" if checklist.keys() <= submitted.keys() else "incomplete",
        ))

    if request.case.ct10 is not None:
        route = result.pathway
        authorization = {
            "prior_intimation": "Dated submission acknowledgement and evidence of manufacture timing.",
            "prior_permission": "Dated CT-11 permission and evidence of manufacture timing.",
        }.get(route, "Evidence needed to establish the route and applicable authorization.")
        add("ct10", f"Explain which CT-10 route applies and why the other route is unsuitable. "
                    f"The dossier evaluation indicates {(route or 'undetermined').replace('_', ' ')}.",
            CT10_SOURCE, {"purpose": "Manufacturing purpose and supporting dossier section.",
                          "classification": "Drug classification and exclusion analysis.",
                          "dates": "Submission date, applicable rule version, and calendar if relevant.",
                          "authorization": authorization})
    if request.case.trial is not None or request.case.ct10 is None or request.case.ct10.purpose == "clinical_trial":
        add("ctri", "Reconcile the CTRI entry with the approved protocol and demonstrate prospective registration.",
            CTRI_SOURCE, {"alignment": "CTRI and protocol identifiers, versions, sponsor, design and sites.",
                          "dates": "Dated registration and first enrolment records or evidence enrolment has yet to start.",
                          "reconciliation": "Explanation of discrepancies and evidence of correction where applicable."})
        add("consent", "Show how each site will obtain understandable consent using the approved versions.",
            CONSENT_SOURCE, {"languages": "Site-language matrix and matching PIS and ICF versions.",
                             "approval": "Dated Ethics Committee approval for each version in use.",
                             "comprehension": "Disclosure review and documented participant comprehension process."})
        population = request.population or "population details pending"
        add("population", f"Justify recruitment for the proposed population ({population}) and explain the safeguards.",
            RISK_SOURCE, {"selection": "Eligibility criteria and scientific rationale for the proposed population.",
                          "safeguards": "Risk mitigation and protections for any vulnerable participants.",
                          "monitoring": "Safety monitoring, stopping criteria and escalation plan."})
    return dict(ruleset_version=VERSION, dossier_ruleset_version=result.ruleset_version,
                case_ref=result.case_ref, as_of=result.as_of.isoformat(), notice=NOTICE,
                questions=questions, unexpected_queries=sorted(request.responses.keys() - {q["id"] for q in questions}))
