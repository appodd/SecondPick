import { request } from "./client";
import type { Monitor } from "./monitorClient";
import type { AssessmentBatch } from "./types";

export interface ProjectDraft {
  title: string;
  goal: string;
  budget: number | null;
  hard: string[];
  soft: string[];
  minimum: number;
  auto_research: boolean;
  auto_cover_cache?: boolean;
}
export interface ProjectCard {
  current_quote?: CurrentQuote | null;
  image_url?: string | null;
  product_images?:{state:string;source_count:number;local_count:number;cover_url:string|null;cover_media_id:number|null};
  updated_at?: string | null;
  listing_id: number;
  title: string;
  url: string;
  price_value: number | null;
  price_text: string | null;
  location: string | null;
  seller_name: string | null;
  search_condition: string | null;
  detail_status: string;
  research_state: string;
  source_run_ids: number[];
}
export interface CurrentQuote { status: string; valid: boolean; amount: string | null; price_text?: string | null; observed_at?: string | null; recorded_at?: string | null; time_basis?: string; reason: string; warnings: string[] }
export interface MarketLayer { count: number; member_ids: number[]; summary: { count: number; min: number | null; max: number | null; q1: number | null; median: number | null; q3: number | null }; position: string }
export interface MarketReference { target_id: number; as_of: string; current_quote: CurrentQuote | null; model: string | null; condition: string; state: string; comparison_dimensions?: string[]; unavailable_reason?: string | null; missing_attribute_peers?: number; criteria: { broad: string; strict: string }; broad: MarketLayer; strict: MarketLayer; peer_total: number; excluded_count: number; exclusion_counts: Record<string, number>; excluded: { listing_id: number; reason: string }[]; strict_excluded: { listing_id: number; reason: string }[]; limitations: string[]; data_digest: string }
export interface ProjectMarket { comparison_version?: number; unavailable_reason?: string | null; as_of: string; scope_count: number; references: Record<string, MarketReference>; profiles: Record<string, { category: string; model: string | null; chip: string | null; memory: string | null; storage: string | null; screen: string | null; year: string | null; condition: string }>; groups: { key: string; label: string; scope_note?: string; member_ids: number[]; summary: MarketLayer["summary"] }[] }
export interface Study {
  instruction?: string | null;
  current_listing_ids?: number[];
  id: number;
  origin?: string | null;
  goal_revision?: number | null;
  goal_text?: string | null;
  kind: string;
  state: string;
  listing_ids: number[];
  snapshot_at: string;
  created_at: string;
  finished_at?: string | null;
  error: string | null;
  result: { content: string; candidate_ids: number[]; research?: AssessmentBatch["result"] | null; check_suggestions?: {listing_id:number;question:string;reason:string}[] } | null;
}
export interface Report {
  evidence_current?: boolean;
  goal_snapshot?: { goal: string; budget: number | null; hard: string[]; soft: string[] } | null;
  goal_revision?: number | null;
  is_current_goal?: boolean;
  id: number;
  study_id?: number;
  content: string;
  candidate_ids_json: string;
  snapshot_at: string;
  created_at: string;
  limited: number;
}
export interface ProjectOverview {
  market?: ProjectMarket;
  evidence_work?: { gate: string; reason: string; batch_limit: number; listing_ids: number[];
    items: { listing_id: number; state: string; reason: string; study_id: number | null;
      previous: { assessment: { summary: string; conclusion: string } | null; study_id: number };
      delta: { fields: string[]; before: Record<string, unknown>; after: Record<string, unknown> } }[] };
  integration_work?: { state: string; reason: string; listing_ids: number[]; updates?: { study_id: number; assessment: { summary: string }; item: { listing_id: number }; decision_impacts?: { criterion_id: string; before: string; after: string; reason: string; evidence_refs: string[]; changed_fields: string[] }[] }[] };
  research_work?: { goal_revision: number; total: number; unassessed: number; batch_limit: number;
    counts: Record<"evaluated" | "ready" | "needs_evidence" | "no_priority" | "attempted" | "failed" | "queued" | "running" | "rule_excluded", number>;
    gate: string; reason: string; listing_ids: number[]; quota: "unknown";
    items: { listing_id: number; state: string; reason: string; study_id: number | null }[] };
  region_preference?: { mode: "none" | "preferred" | "restricted"; city: string | null; legacy_city: string | null; legacy_unverified: boolean };
  goal_context?: { current_revision: number; original_goal: string; report_current: boolean; calibration: "pending" | "running" | "current"; legacy_unmerged: boolean; updated_at: string; automatic_calibration_supported: boolean; calibration_work?: { state: "waiting" | "scheduled" | "running" | "current" | "not_needed" | "not_applicable" | "unavailable"; reason: string; listing_ids: number[]; study_id: number | null } };
  coverage_history?: { evaluated: number; summarized_only: number; reusable_evidence: number };
  historical_coverage?: Record<string, number>;
  project: { id: number; title: string; goal: string; status: string };
  policy: {
    budget: number | null;
    hard: string[];
    soft: string[];
    minimum: number;
    paused: number;
    auto_research: number;
    completed?: number;
  };
  phase: string;
  cards: ProjectCard[];
  coverage: Record<string, number>;
  total: number;
  eligible: number;
  pending: number;
  report: Report | null;
  changes: { id: number; content: string; created_at: string }[];
  favorites: number[];
  studies: Study[];
}
export interface SellerProfile {
  seller_id: string | null;
  profile: Record<string, string>;
  result: {
    business_tendency: "personal_like" | "commercial_like" | "unknown";
    reason: string;
    risk_clues: string[];
    unknowns: string[];
  } | null;
  fresh: boolean;
  observed_at: string | null;
  researched_at: string | null;
}
export interface WindowDraft {
  name: string;
  keyword: string;
  mode: "once" | "timed" | "ongoing";
  duration_seconds: number;
  interval_seconds: number;
  max_pages: number;
  max_items: number;
  collect_seller_profiles: boolean;
}
export interface WindowMonitor {
  monitor_id: number;
  name: string;
  mode: WindowDraft["mode"];
  monitor: Monitor;
  duration_seconds: number | null;
  revision: number;
  runs: {
    counts?: { records: number; unique_listings: number };
    config?: WindowDraft | null;
    id: number;
    state: string;
    started_at: string;
    deadline_at: string | null;
    finished_at: string | null;
    error: string | null;
  }[];
}
const path = (id: number) => `/api/projects/${id}`;
const post = (body?: unknown): RequestInit => ({
  method: "POST",
  ...(body ? { body: JSON.stringify(body) } : {}),
});
export const projectApi = {
  seller: (id: number, listing: number) =>
    request<SellerProfile>(`${path(id)}/listings/${listing}/seller`),
  studySeller: (id: number, listing: number) =>
    request<SellerProfile | { id: number }>(
      `${path(id)}/listings/${listing}/seller/studies`,
      post(),
    ),
  draft: (goal: string, current?: {goal:string;budget:number|null;hard:string[];soft:string[]}) =>
    request<ProjectDraft>("/api/project-goal-drafts", post({ goal, ...(current ? {current} : {}) })),
  create: (draft: ProjectDraft, requestKey: string) =>
    request<{ id: number }>(
      "/api/projects",
      post({ ...draft, request_key: requestKey }),
    ),
  monitorDraft: (id: number, goal: string) =>
    request<WindowDraft>(`${path(id)}/monitor-drafts`, post({ goal })),
  overview: (id: number) => request<ProjectOverview>(`${path(id)}/overview`),
  study: (
    id: number,
    ids?: number[],
    question?: string,
    requestKey: string = crypto.randomUUID(),
    expectedGoalRevision?: number,
  ) =>
    request<{ id: number }>(
      `${path(id)}/studies`,
      post({ ids, question, request_key: requestKey, expected_goal_revision: expectedGoalRevision }),
    ),
  saveGoal: (id: number, draft: { goal: string; budget: number | null; hard: string[]; soft: string[] }, expected_revision: number, request_key: string) => request<{ revision: number; saved: boolean }>(`${path(id)}/goal`, { method: "PATCH", body: JSON.stringify({ ...draft, expected_revision, request_key, confirmed: true }) }),
  reports: (id: number, before?: number) => request<{ items: Report[]; has_more: boolean; next_before_id: number | null }>(`${path(id)}/reports${before ? `?before_id=${before}` : ""}`),
  retry: (id: number, run: number) =>
    request(`${path(id)}/studies/${run}/retry`, post()),
  favorite: (id: number, listing: number, saved: boolean) =>
    request(`${path(id)}/favorites/${listing}`, {
      method: saved ? "PUT" : "DELETE",
    }),
  read: (id: number, report: number) =>
    request(`${path(id)}/read`, post({ report_id: report })),
  control: (
    id: number,
    action: "pause" | "resume" | "complete_keep" | "complete_pause",
  ) => request(`${path(id)}/research/${action}`, post()),
  goalHistory: (id: number) => request<{items:{revision:number;goal:string;budget:number|null;hard:string[];soft:string[];created_at:string}[];has_more:boolean}>(`${path(id)}/goal/history`),
  monitors: (id: number) =>
    request<{ items: WindowMonitor[] }>(`${path(id)}/monitors`),
  createMonitor: (id: number, draft: WindowDraft, requestKey: string) =>
    request(
      `${path(id)}/monitors`,
      post({ ...draft, request_key: requestKey, confirmed: true }),
    ),
  rerun: (id: number, monitor: number) =>
    request(`${path(id)}/monitors/${monitor}/runs`, post()),
  editMonitor: (id: number, monitor: WindowMonitor, draft: WindowDraft) =>
    request(`${path(id)}/monitors/${monitor.monitor_id}`, {
      method: "PATCH",
      body: JSON.stringify({
        ...draft,
        expected_revision: monitor.revision,
        confirmed: true,
      }),
    }),
};
