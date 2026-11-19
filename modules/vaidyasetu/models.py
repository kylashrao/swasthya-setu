"""Structured evidence supplied to the offline evaluator."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from core.evidence_dates import EvidenceDate

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Outcome = Literal["pass", "fail", "review"]
Pathway = Literal["prior_permission", "prior_intimation", "undetermined"]
DrugClass = Literal[
    "other", "sex_hormone", "cytotoxic", "beta_lactam",
    "live_microorganism_biologic", "narcotic", "psychotropic",
]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatedEvidence(Record):
    date: EvidenceDate
    reference: Text


class WorkingCalendar(Record):
    reference: Text
    valid_from: EvidenceDate
    valid_through: EvidenceDate
    working_weekdays: Annotated[
        frozenset[Annotated[int, Field(strict=True, ge=0, le=6)]], Field(min_length=1)
    ]
    holidays: frozenset[EvidenceDate]


class CT10(Record):
    purpose: Literal[
        "analytical_testing", "nonclinical_testing", "clinical_trial",
        "bioavailability", "bioequivalence", "other_test_and_analysis",
    ] | None = None
    drug_classes: Annotated[frozenset[DrugClass], Field(min_length=1)] | None = None
    received: DatedEvidence | None = None
    submitted_as: Literal["prior_permission", "prior_intimation"] | None = None
    acknowledgement: DatedEvidence | None = None
    authority_response: DatedEvidence | None = None
    response_type: Literal["ct11", "rejection", "deficiency_notice"] | None = None
    resubmission_received: DatedEvidence | None = None
    resubmission_decision: DatedEvidence | None = None
    resubmission_decision_type: Literal["ct11", "rejection"] | None = None
    manufacture_started: DatedEvidence | None = None


class TrialDocument(Record):
    reference: Text
    protocol_id: Text | None = None
    protocol_version: Text | None = None
    ctri_id: Text | None = None
    sponsor: Text | None = None
    design: Text | None = None
    india_sites: Annotated[frozenset[Text], Field(min_length=1)] | None = None


class RegistryRecord(TrialDocument):
    registered_on: EvidenceDate | None = None
    actual_first_enrolment: EvidenceDate | None = None


class ConsentDocument(Record):
    reference: Text
    version: Text | None = None
    ec_approved_version: Text | None = None
    approval: DatedEvidence | None = None
    readable: StrictBool | None = None


class ConsentPack(Record):
    site: Text
    language: Text
    protocol_id: Text | None = None
    protocol_version: Text | None = None
    information_sheet: ConsentDocument | None = None
    written_form: ConsentDocument | None = None
    # Evidence references keyed by checklist item. An empty mapping means reviewed
    # and empty, while null means the content has not been assessed.
    elements: dict[Text, Text] | None = None
    language_review: DatedEvidence | None = None
    language_understandable: StrictBool | None = None
    first_used_on: EvidenceDate | None = None


class TrialEvidence(Record):
    protocol: TrialDocument | None = None
    registry: RegistryRecord | None = None
    supporting_documents: tuple[TrialDocument, ...] = ()
    first_enrolment: DatedEvidence | None = None
    enrolment_started: StrictBool | None = None
    # Use the same site identifiers as the protocol and normalized language tags.
    required_languages: dict[Text, frozenset[Text]] | None = None
    consent_packs: tuple[ConsentPack, ...] = ()
    randomized: StrictBool | None = None
    placebo_controlled: StrictBool | None = None
    prorated_payment: StrictBool | None = None
    additional_required_elements: frozenset[Text] = frozenset()


class Case(Record):
    case_ref: Text
    as_of: EvidenceDate
    ct10: CT10 | None = None
    calendar: WorkingCalendar | None = None
    trial: TrialEvidence | None = None


class Finding(Record):
    rule_id: Text
    outcome: Outcome
    source_ref: Text
    message: Text
    evidence_refs: tuple[str, ...]


class Evaluation(Record):
    case_ref: Text
    as_of: EvidenceDate
    ruleset_version: Text
    pathway: Pathway | None
    working_days: int | None
    response_due_on: EvidenceDate | None
    resubmission_due_on: EvidenceDate | None
    findings: tuple[Finding, ...]
