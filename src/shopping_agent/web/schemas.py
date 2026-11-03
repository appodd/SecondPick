from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from shopping_agent.assessment import Criterion, ResearchResult
from shopping_agent.history_review import ComparisonResult
from pydantic import Field, JsonValue


class WorkbenchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


CheckState = Literal["pending", "evidence_linked", "dismissed"]


class CandidateCheck(WorkbenchModel):
    id: int
    task_id: int
    listing_id: int
    question: str
    created_at: str
    revision_id: int
    state: CheckState
    effective_state: CheckState
    statement_id: int | None
    statement_revision_id: int | None
    statement_kind: Literal["seller_reply", "user_observation"] | None
    statement_text: str | None
    note: str | None
    changed_at: str | None
    evidence_current: bool
    needs_recheck: bool


class CheckStatementOption(WorkbenchModel):
    id: int
    revision_id: int
    kind: Literal["seller_reply", "user_observation"]
    statement_text: str


class CandidateCheckPage(WorkbenchModel):
    items: list[CandidateCheck]
    total_count: int
    counts: dict[CheckState, int]
    has_more: bool
    next_before_id: int | None
    available_statements: list[CheckStatementOption]
    statement_count: int
    statements_truncated: bool


class CheckReviewSource(WorkbenchModel):
    statement_id: int
    revision_id: int
    kind: Literal["seller_reply", "user_observation"]
    statement_text: str | None
    current: bool


class CheckReview(WorkbenchModel):
    id: int
    check_id: int
    check_revision_id: int
    action: Literal["record", "withdraw"]
    outcome: Literal["answered", "uncertain", "conflict"] | None
    summary: str | None
    sources: list[CheckReviewSource]
    status: Literal["current", "needs_recheck", "withdrawn", "superseded"]
    independently_verified: bool
    created_at: str


class CheckReviewPage(WorkbenchModel):
    items: list[CheckReview]
    current_review: CheckReview | None
    latest_review_id: int
    check_revision_id: int
    basis_token: str
    total_count: int
    has_more: bool
    next_before_id: int | None


class CheckSuggestionRecord(WorkbenchModel):
    id: int
    task_id: int
    listing_id: int
    operation_id: int
    source_message_id: int
    question: str
    reason: str
    created_at: str
    check_id: int | None
    accepted_at: str | None
    reused_existing: bool
    stale: bool


class CheckSuggestionPage(WorkbenchModel):
    items: list[CheckSuggestionRecord]
    total_count: int
    has_more: bool
    next_before_id: int | None


class CheckSuggestionAcceptance(WorkbenchModel):
    suggestion_id: int
    check: CandidateCheck
    reused_existing: bool


class TaskListItem(WorkbenchModel):
    id: int
    title: str
    city: str
    status: str
    run_count: int
    report_count: int
    updated_at: str
    operation_state: Literal["queued", "running", "waiting_confirmation", "completed", "failed", "cancelled", "interrupted"] | None = None


class TaskListPageInfo(WorkbenchModel):
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None


class TaskListPage(WorkbenchModel):
    items: list[TaskListItem]
    total_count: int
    returned_count: int
    truncated: bool
    page: TaskListPageInfo


class TaskRecord(WorkbenchModel):
    id: int
    title: str
    goal: str
    original_goal: str
    effective_goal: str
    city: str
    status: str
    notes: str | None
    created_at: str
    updated_at: str


class PreferenceRevision(WorkbenchModel):
    id: int
    task_id: int
    user_message: str
    effective_goal: str
    added_preferences: list[str]
    removed_preferences: list[str]
    created_at: str


class RunRecord(WorkbenchModel):
    run_id: int
    role: str
    notes: str | None
    goal: str
    city: str
    query_count: int
    page_snapshot_count: int
    listing_snapshot_count: int
    run_created_at: str
    attached_at: str
    source_queries: list[str]
    source_queries_truncated: bool = False


class ReportRecord(WorkbenchModel):
    id: int
    run_id: int | None
    listing_id: int | None
    title: str
    goal: str | None
    format: str
    created_at: str


class RunCoverage(WorkbenchModel):
    run_id: int
    source_queries: list[str]
    unique_in_run: int
    new_unique_count: int
    cumulative_unique_count: int
    new_unique_ratio: float | None


class SearchCoverage(WorkbenchModel):
    status: str
    unique_candidates: int
    target_min: int
    target_max: int
    marginal_gain_threshold: float
    low_gain_streak: int
    suggested_action: str
    runs: list[RunCoverage]


class RequirementStandard(WorkbenchModel):
    id: int
    task_id: int
    preference_revision_id: int
    operation_id: int
    criteria: list[Criterion]
    created_at: str
    stale: bool


class AssessmentBatch(WorkbenchModel):
    id: int
    task_id: int
    operation_id: int
    batch_index: int
    candidate_ids: list[int]
    standard_id: int
    preference_revision_id: int
    result: ResearchResult
    input_signature: str
    evidence_signature: str
    validity_signature: str
    candidate_stale: dict[str, bool]
    schema_version: str
    prompt_version: str
    evidence_refs: dict[str, JsonValue]
    created_at: str
    stale: bool
    execution_state: Literal["succeeded"]


class ReviewCoverage(WorkbenchModel):
    scope_count: int
    reviewed_count: int
    assessed_count: int
    pending_count: int
    truncated: bool


class NominationProgress(WorkbenchModel):
    required: bool
    total_groups: int
    completed_groups: int
    pending_groups: int


class HistoryReview(WorkbenchModel):
    id: int
    task_id: int
    operation_id: int
    standard_id: int
    preference_revision_id: int
    evidence_signature: str
    state: str
    error_detail: str | None
    stale: bool
    coverage: ReviewCoverage
    nomination_progress: NominationProgress | None = None
    created_at: str


class ComparisonSnapshot(WorkbenchModel):
    id: int
    task_id: int
    operation_id: int
    review_id: int
    standard_id: int
    preference_revision_id: int
    evidence_signature: str
    previous_comparison_id: int | None
    stale: bool
    result: ComparisonResult
    coverage: ReviewCoverage
    created_at: str


class ResearchCounts(WorkbenchModel):
    assessment_batches: int
    reviews: int
    comparisons: int


class ResearchPageInfo(WorkbenchModel):
    limit: int
    has_more: bool
    next_cursor: str | None
    total_counts: ResearchCounts
    returned_counts: ResearchCounts
    preference_revision_id: int
    evidence_signature: str


class ResearchHistory(WorkbenchModel):
    standards: list[RequirementStandard] = Field(default_factory=list)
    assessment_batches: list[AssessmentBatch] = Field(default_factory=list)
    reviews: list[HistoryReview] = Field(default_factory=list)
    comparisons: list[ComparisonSnapshot] = Field(default_factory=list)
    page: ResearchPageInfo | None = None


class TaskHistoryPageInfo(WorkbenchModel):
    limit: int
    has_more: bool
    next_cursor: str | None
    total_counts: dict[str, int]


class TaskHistory(WorkbenchModel):
    preference_revisions: list[PreferenceRevision]
    runs: list[RunRecord]
    reports: list[ReportRecord]
    search_coverage: SearchCoverage
    history_page: TaskHistoryPageInfo | None = None


class TaskDetail(TaskHistory):
    task: TaskRecord
    preference_revision_id: int = 0
    current_preferences: list[str] = Field(default_factory=list)
    current_preferences_truncated: bool = False
    research: ResearchHistory = Field(default_factory=ResearchHistory)


class CandidateStatementBinding(WorkbenchModel):
    id: int
    listing_id: int
    kind: Literal["seller_reply", "user_observation"]
    status: Literal["active", "withdrawn"] = "active"
    revision_id: int = Field(default=0, ge=0)
    original_listing_id: int | None = None


class MessageDto(WorkbenchModel):
    id: int
    task_id: int
    role: Literal["user", "assistant", "system"]
    content: str
    operation_id: int | None
    candidate_ids: list[int]
    candidate_statement: CandidateStatementBinding | None = None
    created_at: str


class OperationDto(WorkbenchModel):
    id: int
    task_id: int
    state: Literal[
        "queued",
        "running",
        "waiting_confirmation",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]
    error_code: str | None
    error_detail: str | None


class ActionRequestDto(WorkbenchModel):
    id: int
    task_id: int
    operation_id: int
    summary: str
    risk: str
    listing_ids: list[int]
    actions: list[Literal["search", "detail", "media", "ocr"]]
    state: Literal["pending", "approved", "rejected"]
    search_query: str | None = None
    max_pages: int = 1


class TaskCreationResponse(WorkbenchModel):
    task: TaskRecord
    message: MessageDto
    operation: OperationDto


class MessageCreationResponse(WorkbenchModel):
    message: MessageDto
    operation: OperationDto


class MessagePage(WorkbenchModel):
    items: list[MessageDto]
    has_more: bool
    next_before_id: int | None


class ActionRequestPage(WorkbenchModel):
    items: list[ActionRequestDto]
    has_more: bool
    next_before_id: int | None


class OperationDetail(WorkbenchModel):
    operation: OperationDto
    last_event_id: int
    action_request: ActionRequestDto | None


class ActionDecisionResponse(WorkbenchModel):
    action_request: ActionRequestDto
    operation: OperationDto


class CandidateScope(WorkbenchModel):
    task_id: int | None
    run_ids: list[int]


class SearchDescriptionSemantics(WorkbenchModel):
    redundant_with_title: str
    missing: str
    distinct: str


class CandidateFieldSemantics(WorkbenchModel):
    search_description: str
    search_description_status: SearchDescriptionSemantics


class CandidatePageInfo(WorkbenchModel):
    offset: int
    limit: int | None
    has_more: bool
    next_cursor: str | None


class MonitorPriceObservation(WorkbenchModel):
    id: int
    round_id: str
    source_run_id: str
    observed_at: str
    imported_at: str
    price: float
    price_text: str | None


class ExternalMonitorSource(WorkbenchModel):
    type: Literal["external_monitor"]
    label: str
    imported_at: str
    source_observed_at: str | None
    independently_verified: Literal[False]
    evidence_stage: Literal["product_record", "search_card"] = "product_record"
    source_round_id: str | None = None
    seller_profile: dict[str, str] = Field(default_factory=dict)
    price_observations: list[MonitorPriceObservation] = Field(default_factory=list)
    price_observation_semantics: str | None = None


class CandidateSummary(WorkbenchModel):
    listing_id: int
    source_run_ids: list[int]
    url: str
    title: str
    search_description: str | None
    search_description_status: Literal[
        "redundant_with_title",
        "missing",
        "distinct",
    ]
    price_text: str | None
    price_value: int | float | None
    location: str | None
    seller_name: str | None
    search_condition: str | None
    has_detail: bool
    detail_status: Literal["captured", "blocked", "not_captured"]
    external_source: ExternalMonitorSource | None = None
    monitor_evidence: dict[str, JsonValue] | None = None
    current_quote: dict[str, JsonValue] | None = None
    market_attributes: dict[str, JsonValue] = Field(default_factory=dict)
    market_provenance: dict[str, JsonValue] = Field(default_factory=dict)
    market_page_fields: dict[str, JsonValue] = Field(default_factory=dict)
    price_history: list[dict[str, JsonValue]] = Field(default_factory=list)


class CandidatePage(WorkbenchModel):
    scope: CandidateScope
    scope_revision: str
    field_semantics: CandidateFieldSemantics
    deduplicated_count: int
    returned_count: int
    page: CandidatePageInfo
    candidates: list[CandidateSummary]


class ListingDetail(WorkbenchModel):
    snapshot_id: int
    run_id: int
    description: str
    attributes: dict[str, str]
    attributes_source: str | None
    evidence_source: str | None
    independently_verified: bool


class SellerFields(WorkbenchModel):
    seller_credit_level: str | None
    seller_registered_days: int | None
    seller_sold_count: int | None
    seller_good_rate: str | None
    seller_realname_verified: bool | None
    seller_reply_rate_24h: str | None
    data_source: Literal["db", "detail_dom_fallback", "mixed", "none"]
    field_sources: dict[str, Literal["db", "detail_dom_fallback", "none"]]
    source: Literal["platform_seller_field"]
    independently_verified: bool


class SellerOtherItem(WorkbenchModel):
    item_id_ext: str | None
    title: str | None
    url: str | None


class EvidenceConflict(WorkbenchModel):
    field: str
    selected_value: str
    selected_source: str
    conflicting_value: str
    conflicting_source: str


class EvidenceCollectionState(WorkbenchModel):
    detail_snapshot_count: int
    valid_detail_snapshot_count: int
    blocked_detail_snapshot_count: int
    listing_lifetime_product_image_count: int
    listing_lifetime_downloaded_product_image_count: int
    listing_lifetime_ocr_result_count: int


class ListingEvidence(CandidateSummary):
    user_statements: list[dict[str, JsonValue]] = Field(default_factory=list)
    user_statement_count: int = 0
    user_statements_truncated: bool = False
    detail: ListingDetail | None
    seller_fields: SellerFields
    seller_other_items: list[SellerOtherItem]
    evidence_conflicts: list[EvidenceConflict]
    collection_state: EvidenceCollectionState
    raw_text_excerpt: str | None


class PriceEvidenceLevel(WorkbenchModel):
    level: str
    label: str
    sample_count: int
    model_use: str
    limitations: list[str]


class PriceSummary(WorkbenchModel):
    count: int
    min: int | float | None
    q1: int | float | None
    median: int | float | None
    q3: int | float | None
    max: int | float | None
    spread: int | float | None
    values: list[int | float]


class NoiseExample(WorkbenchModel):
    listing_id: int
    price_text: str | None
    title: str | None
    url: str


class NoiseExclusionSummary(WorkbenchModel):
    signal_key: str
    count: int
    listing_ids: list[int]
    examples: list[NoiseExample]


class MarketSamplePolicy(WorkbenchModel):
    included: str
    excluded_noise_signal_keys: list[str]
    priced_candidate_count: int
    unpriced_candidate_count: int
    excluded_noise_sample_count: int
    exclusion_summary: list[NoiseExclusionSummary]


class MarketOverall(WorkbenchModel):
    candidate_count: int
    priced_candidate_count: int
    priced_clean_sample_count: int
    priced_excluded_noise_sample_count: int
    source_quality: str
    price_evidence_level: PriceEvidenceLevel
    price_summary: PriceSummary


class ValueCount(WorkbenchModel):
    value: str
    count: int


class MarketSample(WorkbenchModel):
    listing_id: int
    price_text: str | None
    price_value: int | float
    location: str | None
    seller_name: str | None
    title: str | None
    url: str


class SpecPriceGroup(WorkbenchModel):
    group_id: str
    spec_tokens: list[str]
    sample_count: int
    source_quality: str
    price_evidence_level: PriceEvidenceLevel
    price_summary: PriceSummary
    listing_ids: list[int]
    locations: list[ValueCount]
    platforms: list[ValueCount]
    samples: list[MarketSample]


class NearDuplicatePriceSummary(WorkbenchModel):
    count: int
    min: int | float | None
    max: int | float | None
    spread: int | float
    values: list[int | float]


class NearDuplicateMember(WorkbenchModel):
    listing_id: int
    title: str | None
    price_text: str | None
    price_value: int | float | None
    location: str | None
    seller_name: str | None
    source_type: str
    source_label: str
    url: str


class NearDuplicateGroup(WorkbenchModel):
    group_id: str
    confidence: str
    listing_ids: list[int]
    reason_codes: list[str]
    shared_spec_tokens: list[str]
    price_summary: NearDuplicatePriceSummary
    members: list[NearDuplicateMember]
    model_note: str


class MarketGeography(WorkbenchModel):
    locations: list[ValueCount]
    target_city_count: int
    target_city_coverage_ratio: float | None


class MarketCollectionCoverage(WorkbenchModel):
    collection_rounds: int
    listing_snapshot_count: int
    duplicate_count: int
    duplicate_rate: float | None
    captured_detail_count: int
    blocked_detail_count: int
    not_captured_detail_count: int
    detail_coverage_ratio: float | None


class MarketOverview(WorkbenchModel):
    goal: str | None
    target_city: str
    run_ids: list[int]
    decision_owner: Literal["llm"]
    is_final_recommendation: bool
    source_scope: Literal["local_candidate_pool_only"]
    price_evidence_level: PriceEvidenceLevel
    notes: list[str]
    sample_policy: MarketSamplePolicy
    overall: MarketOverall
    spec_price_groups: list[SpecPriceGroup]
    near_duplicate_groups: list[NearDuplicateGroup]
    suggested_llm_checks: list[str]
    geography: MarketGeography
    collection_coverage: MarketCollectionCoverage
    search_coverage: SearchCoverage


class PlatformAccessEvent(WorkbenchModel):
    id: int
    platform: str
    operation: str
    target: str | None
    attempted_at: str


class GlobalPlatformAccessEvents(WorkbenchModel):
    scope: Literal["global"]
    warning: str
    events: list[PlatformAccessEvent]


class DebugSnapshot(WorkbenchModel):
    task: TaskRecord
    runs: list[RunRecord]
    reports: list[ReportRecord]
    search_coverage: SearchCoverage
    global_platform_access_events: GlobalPlatformAccessEvents
