"""Strict contracts: LLM output cannot alter fixed safety rules."""
from typing import Literal, Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Processor = Literal["PROC_A", "PROC_B", "PROC_C", "PROC_D"]
PATCH_FIELDS = {
    "amount_tolerance_cents": "processor_amount_tolerance_cents",
    "settlement_window_days": "processor_settlement_window_days",
    "fixed_fee_cents": "processor_fixed_fee_cents",
    "fee_bps": "processor_fee_bps",
}
PATCH_PATHS = {
    "amount_tolerance_cents": ("amount_matching", "absolute_tolerance_cents"),
    "settlement_window_days": ("settlement", "window_business_days"),
    "fixed_fee_cents": ("fees", "fixed_fee_cents"),
    "fee_bps": ("fees", "percentage_bps"),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchingPolicy(StrictModel):
    relative_tolerance_bps: int = Field(default=0, ge=0, le=25, strict=True)
    maximum_tolerance_cents: int = Field(default=25, ge=0, le=25, strict=True)
    day_basis: Literal["calendar", "business"] = "calendar"
    processor_weekend_grace_days: dict[Processor, Annotated[int, Field(ge=0, le=2, strict=True)]] = Field(
        default_factory=lambda: {p: 0 for p in ("PROC_A", "PROC_B", "PROC_C", "PROC_D")})
    timezone: str = "America/New_York"
    fee_treatment: Literal["gross_only", "gross_to_net"] = "gross_to_net"
    fee_rounding: Literal["half_up", "half_even"] = "half_up"
    processor_amount_tolerance_cents: dict[Literal["PROC_A", "PROC_B", "PROC_C", "PROC_D"], Annotated[int, Field(ge=0, le=25, strict=True)]] = Field(
        default_factory=lambda: {"PROC_A": 0, "PROC_B": 0, "PROC_C": 0, "PROC_D": 0})
    processor_settlement_window_days: dict[Processor, Annotated[int, Field(ge=0, le=5, strict=True)]] = Field(
        default_factory=lambda: {p: 2 for p in ("PROC_A", "PROC_B", "PROC_C", "PROC_D")})
    processor_fixed_fee_cents: dict[Processor, Annotated[int, Field(ge=0, le=100, strict=True)]] = Field(
        default_factory=lambda: {p: 0 for p in ("PROC_A", "PROC_B", "PROC_C", "PROC_D")})
    processor_fee_bps: dict[Processor, Annotated[int, Field(ge=0, le=300, strict=True)]] = Field(
        default_factory=lambda: {p: 0 for p in ("PROC_A", "PROC_B", "PROC_C", "PROC_D")})

    @field_validator("processor_amount_tolerance_cents", "processor_settlement_window_days",
                     "processor_fixed_fee_cents", "processor_fee_bps", "processor_weekend_grace_days")
    @classmethod
    def all_processors(cls, value, info):
        if set(value) == {"PROC_A", "PROC_B", "PROC_C"}:
            value = {**value, "PROC_D": 2 if info.field_name == "processor_settlement_window_days" else 0}
        if set(value) != {"PROC_A", "PROC_B", "PROC_C", "PROC_D"}:
            raise ValueError("Policy must include all four processors")
        return value


class RetrievalPolicy(StrictModel):
    memory_top_k: int = Field(default=5, ge=1, le=10, strict=True)


class EscalationPolicy(StrictModel):
    confidence_min: float = Field(default=0.7, ge=0.5, le=0.99)


class AmountRules(StrictModel):
    absolute_tolerance_cents: int = Field(default=0, ge=0, le=25, strict=True)
    relative_tolerance_bps: int = Field(default=0, ge=0, le=25, strict=True)
    maximum_tolerance_cents: int = Field(default=25, ge=0, le=25, strict=True)


class SettlementRules(StrictModel):
    window_business_days: int = Field(default=2, ge=0, le=5, strict=True)
    day_basis: Literal["calendar", "business"] = "calendar"
    weekend_grace_days: int = Field(default=0, ge=0, le=2, strict=True)
    timezone: str = "America/New_York"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value


class FeeRules(StrictModel):
    treatment: Literal["gross_only", "gross_to_net"] = "gross_to_net"
    percentage_bps: int = Field(default=0, ge=0, le=300, strict=True)
    fixed_fee_cents: int = Field(default=0, ge=0, le=100, strict=True)
    rounding: Literal["half_up", "half_even"] = "half_up"


class RefundRules(StrictModel):
    enabled: Literal[False] = False
    allow_partial: bool = False
    matching_window_days: int = Field(default=14, ge=1, le=90, strict=True)
    require_original_transaction: Literal[True] = True


class GroupRules(StrictModel):
    enabled: Literal[False] = False
    strategy: Literal["one_to_many"] = "one_to_many"
    maximum_group_size: int = Field(default=3, ge=2, le=5, strict=True)
    require_balanced_total: Literal[True] = True


class ReferenceRules(StrictModel):
    strategy: Literal["exact"] = "exact"
    minimum_similarity: float = Field(default=0.95, ge=0.9, le=1)
    minimum_candidate_margin: float = Field(default=0.1, ge=0.05, le=1)
    python_patch: None = None


class AmountOverride(StrictModel):
    absolute_tolerance_cents: int | None = Field(default=None, ge=0, le=25, strict=True)


class SettlementOverride(StrictModel):
    window_business_days: int | None = Field(default=None, ge=0, le=5, strict=True)
    weekend_grace_days: int | None = Field(default=None, ge=0, le=2, strict=True)


class FeeOverride(StrictModel):
    percentage_bps: int | None = Field(default=None, ge=0, le=300, strict=True)
    fixed_fee_cents: int | None = Field(default=None, ge=0, le=100, strict=True)


class ProcessorOverride(StrictModel):
    amount_matching: AmountOverride = Field(default_factory=AmountOverride)
    settlement: SettlementOverride = Field(default_factory=SettlementOverride)
    fees: FeeOverride = Field(default_factory=FeeOverride)


class Policy(StrictModel):
    processor_names: dict[Processor, str] = Field(default_factory=lambda: {"PROC_A": "Stripe", "PROC_B": "Adyen", "PROC_C": "PayPal", "PROC_D": "Square"})
    version: str
    parent: str | None = None
    amount_matching: AmountRules = Field(default_factory=AmountRules)
    settlement: SettlementRules = Field(default_factory=SettlementRules)
    fees: FeeRules = Field(default_factory=FeeRules)
    refunds: RefundRules = Field(default_factory=RefundRules)
    group_matching: GroupRules = Field(default_factory=GroupRules)
    reference_matching: ReferenceRules = Field(default_factory=ReferenceRules)
    processor_overrides: dict[Processor, ProcessorOverride] = Field(default_factory=dict)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    escalation: EscalationPolicy = Field(default_factory=EscalationPolicy)

    @field_validator("processor_names")
    @classmethod
    def configured_processor_names(cls, value):
        if set(value) != {"PROC_A", "PROC_B", "PROC_C", "PROC_D"} or any(not name.strip() for name in value.values()):
            raise ValueError("Provide a display name for all four processors")
        return value

    @model_validator(mode="before")
    @classmethod
    def read_legacy_policy(cls, value):
        if not isinstance(value, dict) or "matching" not in value:
            return value
        data = dict(value)
        if any(key in data for key in ("amount_matching", "settlement", "fees", "processor_overrides")):
            raise ValueError("Use named policy rules or legacy matching maps, not both")
        legacy = MatchingPolicy.model_validate(data.pop("matching"))
        data["amount_matching"] = {"relative_tolerance_bps": legacy.relative_tolerance_bps,
                                   "maximum_tolerance_cents": legacy.maximum_tolerance_cents}
        data["settlement"] = {"day_basis": legacy.day_basis, "timezone": legacy.timezone}
        data["fees"] = {"treatment": legacy.fee_treatment, "rounding": legacy.fee_rounding}
        overrides = {}
        for processor in ("PROC_A", "PROC_B", "PROC_C", "PROC_D"):
            entry = {}
            for patch, field in PATCH_FIELDS.items():
                group, parameter = PATCH_PATHS[patch]
                parameter_value = getattr(legacy, field)[processor]
                default = 2 if patch == "settlement_window_days" else 0
                if parameter_value != default:
                    entry.setdefault(group, {})[parameter] = parameter_value
            if legacy.processor_weekend_grace_days[processor]:
                entry.setdefault("settlement", {})["weekend_grace_days"] = legacy.processor_weekend_grace_days[processor]
            if entry:
                overrides[processor] = entry
        data["processor_overrides"] = overrides
        return data

    def model_dump(self, **kwargs):
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(**kwargs)

    @property
    def matching(self):
        values = {field: {} for field in PATCH_FIELDS.values()}
        grace = {}
        for processor in ("PROC_A", "PROC_B", "PROC_C", "PROC_D"):
            override = self.processor_overrides.get(processor, ProcessorOverride())
            for patch, field in PATCH_FIELDS.items():
                group, parameter = PATCH_PATHS[patch]
                value = getattr(getattr(override, group), parameter)
                values[field][processor] = getattr(getattr(self, group), parameter) if value is None else value
            grace_value = override.settlement.weekend_grace_days
            grace[processor] = self.settlement.weekend_grace_days if grace_value is None else grace_value
        return MatchingPolicy(**values, relative_tolerance_bps=self.amount_matching.relative_tolerance_bps,
            maximum_tolerance_cents=self.amount_matching.maximum_tolerance_cents,
            day_basis=self.settlement.day_basis, processor_weekend_grace_days=grace,
            timezone=self.settlement.timezone, fee_treatment=self.fees.treatment, fee_rounding=self.fees.rounding)


class DiagnosisResult(StrictModel):
    hypothesis: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    alternative_hypotheses: list[str] = Field(default_factory=list)
    requested_analyses: list[str] = Field(default_factory=list)
    status: Literal["READY_FOR_ANALYSIS", "READY_FOR_MEMORY_SEARCH", "NEED_MORE_EVIDENCE"]


class MemoryResult(StrictModel):
    memory_ids: list[str]
    relevance: str


class AnalysisResult(StrictModel):
    memory_ids: list[str]
    evidence_summary: str
    relevance: str
    supported_processor: Processor
    confidence: float = Field(ge=0, le=1)
    status: Literal["READY_FOR_EVOLUTION", "NEED_MORE_EVIDENCE"]


class PolicyPatch(StrictModel):
    processor: Processor
    amount_tolerance_cents: int | None = Field(default=None, ge=0, le=25, strict=True)
    settlement_window_days: int | None = Field(default=None, ge=0, le=5, strict=True)
    fixed_fee_cents: int | None = Field(default=None, ge=0, le=100, strict=True)
    fee_bps: int | None = Field(default=None, ge=0, le=300, strict=True)

    @model_validator(mode="after")
    def exactly_one_change(self):
        if sum(getattr(self, key) is not None for key in PATCH_FIELDS) != 1:
            raise ValueError("A patch must specify exactly one policy field")
        return self

    def change(self):
        key = next(key for key in PATCH_FIELDS if getattr(self, key) is not None)
        return key, PATCH_FIELDS[key], getattr(self, key)


class EvolutionResult(StrictModel):
    parent_version: str
    candidate_patch: PolicyPatch
    reason: str
    expected_effect: str
    risk: str
    required_eval_slices: list[str] = Field(default_factory=list)


class MatchSuggestion(StrictModel):
    internal_record_id: str
    processor_record_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str


def apply_patch(base: Policy, proposal: EvolutionResult, version: str) -> Policy:
    if proposal.parent_version != base.version:
        raise ValueError("Candidate references a stale parent policy")
    data = base.model_dump()
    data.update(version=version, parent=base.version)
    patch = proposal.candidate_patch
    _, field, value = patch.change()
    if getattr(base.matching, field)[patch.processor] == value:
        raise ValueError("Patch must change one policy field; no-op versions are not allowed")
    key, _, _ = patch.change()
    group, parameter = PATCH_PATHS[key]
    data.setdefault("processor_overrides", {}).setdefault(patch.processor, {}).setdefault(group, {})[parameter] = value
    return Policy.model_validate(data)
