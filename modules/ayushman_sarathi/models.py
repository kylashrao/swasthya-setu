"""Local tariff, admission and attachment evidence contracts."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, NonNegativeInt, StrictBool, StringConstraints, model_validator,
)

from core.evidence_dates import EvidenceDate, EvidenceTimestamp

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PackageCode = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1)]
Paise = Annotated[int, Field(strict=True, ge=0)]
BasisPoints = Annotated[int, Field(strict=True, ge=0, le=10_000)]
Outcome = Literal["pass", "fail", "review"]
Stage = Literal["preauthorization", "claim"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttachmentRule(Record):
    kind: Text
    scope: Literal["admission", "procedure"]
    deadline: Literal["preauthorization", "preoperative", "both"]
    text_required: StrictBool = True


class Package(Record):
    code: PackageCode
    procedure_keys: Annotated[frozenset[Text], Field(min_length=1)]
    kind: Literal["surgical", "medical"]
    tariff_paise: Paise
    source_ref: Text
    preop_checklist: tuple[AttachmentRule, ...]
    preauthorization_required: StrictBool


class CombinationOverride(Record):
    package_codes: Annotated[frozenset[PackageCode], Field(min_length=2)]
    rank_basis_points: Annotated[tuple[BasisPoints, ...], Field(min_length=2)]
    source_ref: Text

    @model_validator(mode="after")
    def rates_cover_combination(self):
        if len(self.package_codes) != len(self.rank_basis_points):
            raise ValueError("Supply one rate for each package rank in the combination.")
        return self


class Schedule(Record):
    version: Text
    source_ref: Text
    sha_code: Text
    tariff_profile: Text
    effective_from: EvidenceDate
    effective_through: EvidenceDate | None = None
    packages: Annotated[tuple[Package, ...], Field(min_length=1)]
    surgical_grouping: Literal["admission", "ot_session"]
    surgical_rank_basis_points: Annotated[tuple[BasisPoints, ...], Field(min_length=1)]
    rounding: Literal["half_up", "down"]
    rounding_unit_paise: Literal[1, 100]
    overrides: tuple[CombinationOverride, ...] = ()

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.effective_through and self.effective_through < self.effective_from:
            raise ValueError("The schedule effective period is inverted.")
        packages = {package.code: package for package in self.packages}
        if len(packages) != len(self.packages):
            raise ValueError("Package codes must be unique within a schedule.")
        combinations = {override.package_codes for override in self.overrides}
        if len(combinations) != len(self.overrides):
            raise ValueError("Combination overrides must be unique.")
        surgical = {package.code for package in self.packages if package.kind == "surgical"}
        if any(not codes <= surgical for codes in combinations):
            raise ValueError("Combination overrides must reference scheduled surgical packages.")
        return self


class Procedure(Record):
    line_ref: Text
    source_ref: Text
    procedure_key: Text | None = None
    submitted_code: PackageCode | None = None
    submitted_paise: Paise | None = None
    ot_session_ref: Text | None = None
    surgery_at: EvidenceTimestamp | None = None


class Attachment(Record):
    reference: Text
    kind: Text
    admission_ref: Text | None = None
    line_ref: Text | None = None
    readable: StrictBool | None = None
    has_extractable_text: StrictBool | None = None
    recorded_at: EvidenceTimestamp | None = None
    uploaded_at: EvidenceTimestamp | None = None


class Authorization(Record):
    reference: Text
    admission_ref: Text
    line_ref: Text
    package_code: PackageCode
    approved_at: EvidenceTimestamp


class Admission(Record):
    admission_ref: Text
    stage: Stage
    as_of: EvidenceTimestamp
    sha_code: Text
    tariff_profile: Text
    tariff_date: EvidenceDate
    preauthorization_submitted_at: EvidenceTimestamp | None = None
    procedures: tuple[Procedure, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    authorizations: tuple[Authorization, ...] = ()
    submitted_total_paise: Paise | None = None

    @model_validator(mode="after")
    def validate_evidence_links(self):
        if len({line.line_ref for line in self.procedures}) != len(self.procedures):
            raise ValueError("Procedure line references must be unique within an admission.")
        by_reference = {}
        for attachment in self.attachments:
            if by_reference.setdefault(attachment.reference, attachment) != attachment:
                raise ValueError("An attachment reference has conflicting evidence metadata.")
        return self


class Finding(Record):
    rule_id: Text
    outcome: Outcome
    source_ref: Text
    message: Text
    evidence_refs: tuple[str, ...]
    line_ref: Text | None = None


class LineRate(Record):
    line_ref: Text
    package_code: PackageCode
    rank: Annotated[int, Field(ge=1)]
    tariff_paise: Paise
    basis_points: BasisPoints
    expected_paise: Paise
    source_ref: Text


class Evaluation(Record):
    admission_ref: Text
    stage: Stage
    as_of: EvidenceTimestamp
    ruleset_version: Text
    schedule_version: Text | None
    line_rates: tuple[LineRate, ...]
    expected_total_paise: NonNegativeInt | None
    findings: tuple[Finding, ...]
