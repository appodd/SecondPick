export interface ApiErrorEnvelope {
  error?: {
    code: string;
    message: string;
  };
}

export type OperationState = "queued" | "running" | "waiting_confirmation" | "completed" | "failed" | "cancelled" | "interrupted";
export interface OperationDto {
  id: number; task_id: number; state: OperationState;
  error_code: string | null; error_detail: string | null;
}
export interface MessageDto {
  candidate_statement?: CandidateStatementBinding | null;
  id: number; task_id: number; role: "user" | "assistant" | "system";
  content: string; operation_id: number | null; candidate_ids: number[]; created_at: string;
}
export interface CandidateStatementInput { listing_id: number; kind: "seller_reply" | "user_observation" }
export interface CandidateStatementBinding extends CandidateStatementInput {
  id: number; status?: "active" | "withdrawn"; revision_id?: number; original_listing_id?: number | null;
}
export type StatementChange = { action: "withdraw"; expected_revision_id: number } |
  ({ action: "rebind"; expected_revision_id: number } & CandidateStatementInput);
export interface ActionRequestDto {
  id: number; task_id: number; operation_id: number; summary: string; risk: string;
  listing_ids: number[]; actions: ("search" | "detail" | "media" | "ocr")[];
  state: "pending" | "approved" | "rejected";
  search_query?: string | null; max_pages?: number;
}
export interface HistoryPage<T> { items: T[]; has_more: boolean; next_before_id: number | null }
export interface OperationDetail { operation: OperationDto; last_event_id: number; action_request: ActionRequestDto | null }
export interface MessageCreationResponse { message: MessageDto; operation: OperationDto }
export interface TaskCreationResponse extends MessageCreationResponse { task: TaskRecord }
export interface ActionDecisionResponse { action_request: ActionRequestDto; operation: OperationDto }

export interface SetupCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface CodexStatus {
  cli_available: boolean;
  auth_available: boolean;
  process_running: boolean;
  detail: string;
}

export interface XianyuStatus {
  profile_present: boolean;
  auth_status: "unknown" | "verified" | "invalid";
  detail: string;
}

export interface SetupStatus {
  setup_completed: boolean;
  environment: SetupCheck[];
  codex: CodexStatus;
  xianyu: XianyuStatus;
  can_browse_existing_data: boolean;
  can_start_research: boolean;
}

export interface UserSettings {
  setup_completed: boolean;
  setup_mode?: "basic" | "ai";
  default_city: string | null;
  platforms: string[];
  allow_ocr: boolean;
  preferred_view: "research" | "debug";
}

export type SettingsPatch = Partial<UserSettings>;

export interface TaskListItem {
  id: number;
  title: string;
  city: string;
  status: string;
  run_count: number;
  report_count: number;
  updated_at: string;
  operation_state?: OperationState | null;
}

export interface TaskListResponse {
  items: TaskListItem[];
  total_count: number;
  returned_count: number;
  truncated: boolean;
  page: TaskListPageInfo;
}

export interface TaskListPageInfo {
  offset: number;
  limit: number;
  has_more: boolean;
  next_offset: number | null;
}

export interface TaskRecord {
  id: number;
  title: string;
  goal: string;
  original_goal: string;
  effective_goal: string;
  city: string;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PreferenceRevision {
  id: number;
  task_id: number;
  user_message: string;
  effective_goal: string;
  added_preferences: string[];
  removed_preferences: string[];
  created_at: string;
}

export interface RunRecord {
  run_id: number;
  role: string;
  notes: string | null;
  goal: string;
  city: string;
  query_count: number;
  page_snapshot_count: number;
  listing_snapshot_count: number;
  run_created_at: string;
  attached_at: string;
  source_queries: string[];
  source_queries_truncated?: boolean;
}

export interface ReportRecord {
  id: number;
  run_id: number | null;
  listing_id: number | null;
  title: string;
  goal: string | null;
  format: string;
  created_at: string;
}

export interface RunCoverage {
  run_id: number;
  source_queries: string[];
  unique_in_run: number;
  new_unique_count: number;
  cumulative_unique_count: number;
  new_unique_ratio: number | null;
}

export interface SearchCoverage {
  status: string;
  unique_candidates: number;
  target_min: number;
  target_max: number;
  marginal_gain_threshold: number;
  low_gain_streak: number;
  suggested_action: string;
  runs: RunCoverage[];
}

export interface TaskDetail {
  task: TaskRecord;
  preference_revisions: PreferenceRevision[];
  runs: RunRecord[];
  reports: ReportRecord[];
  search_coverage: SearchCoverage;
  research?: ResearchHistory;
  history_page?: TaskHistoryPageInfo | null;
  preference_revision_id?: number;
  current_preferences?: string[];
  current_preferences_truncated?: boolean;
}

export interface TaskHistoryPageInfo {
  limit: number; has_more: boolean; next_cursor: string | null;
  total_counts: { preference_revisions: number; runs: number; reports: number };
}
export type TaskHistory = Pick<TaskDetail, "preference_revisions" | "runs" | "reports" | "search_coverage" | "history_page">;

export interface ResearchHistory {
  standards: RequirementStandard[]; assessment_batches: AssessmentBatch[];
  reviews?: HistoryReview[]; comparisons?: ComparisonSnapshot[];
  page?: { limit: number; has_more: boolean; next_cursor: string | null;
    total_counts: ResearchCounts; returned_counts: ResearchCounts;
    preference_revision_id: number; evidence_signature: string } | null;
}

export interface ResearchCounts { assessment_batches: number; reviews: number; comparisons: number }

export interface Criterion {
  criterion_id: string;
  description: string;
  priority: "hard" | "soft";
  source_message_ids: number[];
  source_refs?: string[];
}

export interface CriterionJudgment {
  criterion_id: string;
  status: "MET" | "NOT_MET" | "UNKNOWN" | "CONFLICT";
  reason: string;
  source_type: "seller_claim" | "platform_display" | "image_observation" | "user_statement" | "inference" | "missing";
  evidence_refs: string[];
}

export interface RequirementStandard {
  id: number; task_id: number; operation_id: number; preference_revision_id: number;
  criteria: Criterion[]; created_at: string; stale: boolean;
}

export interface AssessmentBatch {
  id: number; task_id: number; operation_id: number; standard_id: number;
  preference_revision_id: number; stale: boolean; execution_state: "succeeded";
  input_signature: string; evidence_signature: string; schema_version: string; prompt_version: string;
  validity_signature?: string; candidate_stale?: Record<string, boolean>;
  created_at: string; evidence_refs: Record<string, unknown>;
  batch_index?: number; candidate_ids?: number[];
  result: { criteria: Criterion[]; assessments: {
    listing_id: number; judgments: CriterionJudgment[];
    conclusion: "consider" | "conditional" | "not_met" | "insufficient_evidence";
    summary: string;
  }[] };
}

export interface ReviewCoverage {
  scope_count: number; reviewed_count: number; assessed_count: number; pending_count: number; truncated: boolean;
}

export interface HistoryReview {
  nomination_progress?: { required: boolean; total_groups: number; completed_groups: number; pending_groups: number } | null;
  id: number; task_id: number; operation_id: number; standard_id: number; preference_revision_id: number;
  state: string; error_detail: string | null; stale: boolean; coverage: ReviewCoverage; created_at: string;
  evidence_signature?: string;
}

export interface ComparisonSnapshot {
  id: number; task_id: number; operation_id: number; review_id: number; standard_id: number;
  preference_revision_id: number; previous_comparison_id: number | null; stale: boolean;
  created_at: string; coverage: ReviewCoverage;
  evidence_signature?: string;
  result: { type: "comparison"; content: string;
    ranked_candidates: { listing_id: number; assessment_id: number; reason: string; uncertainties: string[] }[];
    changes: { listing_id: number; assessment_id: number; kind: "entered" | "exited"; reason: string }[];
  };
}

export interface PlatformAccessEvent {
  id: number;
  platform: string;
  operation: string;
  target: string | null;
  attempted_at: string;
}

export interface GlobalPlatformAccessEvents {
  scope: "global";
  warning: string;
  events: PlatformAccessEvent[];
}

export interface DebugSnapshot {
  task: TaskRecord;
  runs: RunRecord[];
  reports: ReportRecord[];
  search_coverage: SearchCoverage;
  global_platform_access_events: GlobalPlatformAccessEvents;
}

export interface CandidateScope {
  task_id: number | null;
  run_ids: number[];
}

export interface CandidatePageInfo {
  offset: number;
  limit: number | null;
  has_more: boolean;
  next_cursor: string | null;
}

export interface SearchDescriptionSemantics {
  redundant_with_title: string;
  missing: string;
  distinct: string;
}

export interface CandidateFieldSemantics {
  search_description: string;
  search_description_status: SearchDescriptionSemantics;
}

export interface CandidateSummary {
  current_quote?: import("./projectClient").CurrentQuote | null;
  listing_id: number;
  source_run_ids: number[];
  url: string;
  title: string;
  search_description: string | null;
  search_description_status: "missing" | "redundant_with_title" | "distinct";
  price_text: string | null;
  price_value: number | null;
  location: string | null;
  seller_name: string | null;
  search_condition: string | null;
  has_detail: boolean;
  detail_status: "captured" | "blocked" | "not_captured";
}

export interface CandidatePage {
  scope: CandidateScope;
  scope_revision: string;
  field_semantics: CandidateFieldSemantics;
  deduplicated_count: number;
  returned_count: number;
  page: CandidatePageInfo;
  candidates: CandidateSummary[];
}

export type CheckState = "pending" | "evidence_linked" | "dismissed";
export interface CandidateCheck {
  id: number; task_id: number; listing_id: number; question: string; created_at: string;
  revision_id: number; state: CheckState; effective_state: CheckState;
  statement_id: number | null; statement_revision_id: number | null;
  statement_kind: "seller_reply" | "user_observation" | null; statement_text: string | null;
  note: string | null; changed_at: string | null; evidence_current: boolean; needs_recheck: boolean;
}
export interface CheckStatementOption { id: number; revision_id: number; kind: "seller_reply" | "user_observation"; statement_text: string }
export interface CandidateCheckPage {
  items: CandidateCheck[]; total_count: number; counts: Record<CheckState, number>;
  has_more: boolean; next_before_id: number | null; available_statements: CheckStatementOption[];
  statement_count: number; statements_truncated: boolean;
}
export interface CheckChange { expected_revision_id: number; state: CheckState; statement_id?: number; statement_revision_id?: number; note?: string }

export interface ListingEvidence extends CandidateSummary {
  user_statements?: { id: number; source_message_id: number; kind: "seller_reply" | "user_observation";
    statement_text: string; independently_verified: boolean; created_at: string }[];
  user_statement_count?: number; user_statements_truncated?: boolean;
  detail_status: "captured" | "blocked" | "not_captured";
  detail: ListingDetail | null;
  seller_fields: SellerFields;
  seller_other_items: SellerOtherItem[];
  evidence_conflicts: EvidenceConflict[];
  collection_state: EvidenceCollectionState;
  raw_text_excerpt: string | null;
}

export interface ListingDetail {
  snapshot_id: number;
  run_id: number;
  description: string;
  attributes: Record<string, string>;
  attributes_source: string | null;
  evidence_source: string | null;
  independently_verified: boolean;
}

export interface SellerFields {
  seller_credit_level: string | null;
  seller_registered_days: number | null;
  seller_sold_count: number | null;
  seller_good_rate: string | null;
  seller_realname_verified: boolean | null;
  seller_reply_rate_24h: string | null;
  data_source: "db" | "detail_dom_fallback" | "mixed" | "none";
  field_sources: Record<
    string,
    "db" | "detail_dom_fallback" | "none"
  >;
  source: "platform_seller_field";
  independently_verified: boolean;
}

export interface SellerOtherItem {
  item_id_ext: string | null;
  title: string | null;
  url: string | null;
}

export interface EvidenceConflict {
  field: string;
  selected_value: string;
  selected_source: string;
  conflicting_value: string;
  conflicting_source: string;
}

export interface EvidenceCollectionState {
  detail_snapshot_count: number;
  valid_detail_snapshot_count: number;
  blocked_detail_snapshot_count: number;
  listing_lifetime_product_image_count: number;
  listing_lifetime_downloaded_product_image_count: number;
  listing_lifetime_ocr_result_count: number;
}

export interface PriceEvidenceLevel {
  level: string;
  label: string;
  sample_count: number;
  model_use: string;
  limitations: string[];
}

export interface PriceSummary {
  count: number;
  min: number | null;
  q1: number | null;
  median: number | null;
  q3: number | null;
  max: number | null;
  spread: number | null;
  values: number[];
}

export interface NoiseExample {
  listing_id: number;
  price_text: string | null;
  title: string | null;
  url: string;
}

export interface NoiseExclusionSummary {
  signal_key: string;
  count: number;
  listing_ids: number[];
  examples: NoiseExample[];
}

export interface MarketSamplePolicy {
  included: string;
  excluded_noise_signal_keys: string[];
  priced_candidate_count: number;
  unpriced_candidate_count: number;
  excluded_noise_sample_count: number;
  exclusion_summary: NoiseExclusionSummary[];
}

export interface MarketOverall {
  candidate_count: number;
  priced_candidate_count: number;
  priced_clean_sample_count: number;
  priced_excluded_noise_sample_count: number;
  source_quality: string;
  price_evidence_level: PriceEvidenceLevel;
  price_summary: PriceSummary;
}

export interface ValueCount {
  value: string;
  count: number;
}

export interface MarketSample {
  listing_id: number;
  price_text: string | null;
  price_value: number;
  location: string | null;
  seller_name: string | null;
  title: string | null;
  url: string;
}

export interface SpecPriceGroup {
  group_id: string;
  spec_tokens: string[];
  sample_count: number;
  source_quality: string;
  price_evidence_level: PriceEvidenceLevel;
  price_summary: PriceSummary;
  listing_ids: number[];
  locations: ValueCount[];
  platforms: ValueCount[];
  samples: MarketSample[];
}

export interface NearDuplicatePriceSummary {
  count: number;
  min: number | null;
  max: number | null;
  spread: number;
  values: number[];
}

export interface NearDuplicateMember {
  listing_id: number;
  title: string | null;
  price_text: string | null;
  price_value: number | null;
  location: string | null;
  seller_name: string | null;
  source_type: string;
  source_label: string;
  url: string;
}

export interface NearDuplicateGroup {
  group_id: string;
  confidence: string;
  listing_ids: number[];
  reason_codes: string[];
  shared_spec_tokens: string[];
  price_summary: NearDuplicatePriceSummary;
  members: NearDuplicateMember[];
  model_note: string;
}

export interface MarketOverview {
  goal: string | null;
  target_city: string;
  run_ids: number[];
  decision_owner: "llm";
  is_final_recommendation: boolean;
  source_scope: "local_candidate_pool_only";
  price_evidence_level: PriceEvidenceLevel;
  notes: string[];
  sample_policy: MarketSamplePolicy;
  overall: MarketOverall;
  spec_price_groups: SpecPriceGroup[];
  near_duplicate_groups: NearDuplicateGroup[];
  suggested_llm_checks: string[];
  geography: MarketGeography;
  collection_coverage: MarketCollectionCoverage;
  search_coverage: SearchCoverage;
}

export interface MarketGeography {
  locations: ValueCount[];
  target_city_count: number;
  target_city_coverage_ratio: number | null;
}

export interface MarketCollectionCoverage {
  collection_rounds: number;
  listing_snapshot_count: number;
  duplicate_count: number;
  duplicate_rate: number | null;
  captured_detail_count: number;
  blocked_detail_count: number;
  not_captured_detail_count: number;
  detail_coverage_ratio: number | null;
}
export interface CheckSuggestionRecord {
  id: number; task_id: number; listing_id: number; operation_id: number; source_message_id: number;
  question: string; reason: string; created_at: string; check_id: number | null; accepted_at: string | null;
  reused_existing: boolean; stale: boolean;
}
export interface CheckSuggestionPage {
  items: CheckSuggestionRecord[]; total_count: number; has_more: boolean; next_before_id: number | null;
}
export interface CheckSuggestionAcceptance { suggestion_id: number; check: CandidateCheck; reused_existing: boolean }
export type CheckReviewOutcome = "answered" | "uncertain" | "conflict";
export interface CheckReview {
  id: number; check_id: number; check_revision_id: number; action: "record" | "withdraw";
  outcome: CheckReviewOutcome | null; summary: string | null; created_at: string;
  sources: { statement_id: number; revision_id: number; kind: "seller_reply" | "user_observation"; statement_text: string | null; current: boolean }[];
  status: "current" | "needs_recheck" | "withdrawn" | "superseded"; independently_verified: false;
}
export interface CheckReviewPage {
  items: CheckReview[]; current_review: CheckReview | null; latest_review_id: number; check_revision_id: number;
  basis_token: string; total_count: number; has_more: boolean; next_before_id: number | null;
}
export interface CheckReviewChange {
  expected_review_id: number; expected_check_revision_id: number; expected_basis_token: string;
  action: "record" | "withdraw"; outcome?: CheckReviewOutcome; summary?: string;
  sources?: { statement_id: number; revision_id: number }[];
}
