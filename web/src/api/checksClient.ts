import { ApiError, request } from "./client";
import type { CandidateCheck, CandidateCheckPage, CheckChange, CheckSuggestionPage, CheckSuggestionAcceptance, CheckReviewPage, CheckReviewChange, CheckReview } from "./types";

type Obj = Record<string, unknown>;
const object = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const integer = (v: unknown, minimum = 0) => Number.isSafeInteger(v) && Number(v) >= minimum;
const textOrNull = (v: unknown) => v === null || typeof v === "string";
const state = (v: unknown) => v === "pending" || v === "evidence_linked" || v === "dismissed";
const source = (v: unknown) => object(v) && integer(v.id, 1) && integer(v.revision_id) &&
  (v.kind === "seller_reply" || v.kind === "user_observation") && typeof v.statement_text === "string";
const item = (v: unknown, taskId: number, listingId: number) => object(v) && integer(v.id, 1) &&
  v.task_id === taskId && v.listing_id === listingId && typeof v.question === "string" && typeof v.created_at === "string" &&
  integer(v.revision_id) && state(v.state) && state(v.effective_state) &&
  (v.statement_id === null || integer(v.statement_id, 1)) && (v.statement_revision_id === null || integer(v.statement_revision_id)) &&
  (v.statement_kind === null || v.statement_kind === "seller_reply" || v.statement_kind === "user_observation") &&
  textOrNull(v.statement_text) && textOrNull(v.note) && textOrNull(v.changed_at) && typeof v.evidence_current === "boolean" && typeof v.needs_recheck === "boolean";
function checked<T>(value: unknown, valid: (v: unknown) => boolean): T {
  if (!valid(value)) throw new ApiError({ status: 200, code: "invalid_response", message: "核实清单数据不完整，请刷新重试。" });
  return value as T;
}
const json = (body: unknown, method = "POST") => ({ method, body: JSON.stringify(body) });
const review = (v: unknown, checkId: number) => object(v) && integer(v.id, 1) && v.check_id === checkId && integer(v.check_revision_id) &&
  (v.action === "record" || v.action === "withdraw") && (v.outcome === null || ["answered", "uncertain", "conflict"].includes(String(v.outcome))) &&
  textOrNull(v.summary) && typeof v.created_at === "string" && ["current", "needs_recheck", "withdrawn", "superseded"].includes(String(v.status)) && v.independently_verified === false &&
  Array.isArray(v.sources) && v.sources.length <= 5 && v.sources.every(s => object(s) && integer(s.statement_id, 1) && integer(s.revision_id) &&
    (s.kind === "seller_reply" || s.kind === "user_observation") && textOrNull(s.statement_text) && typeof s.current === "boolean");
export const checksClient = {
  async getCheckReviews(taskId: number, listingId: number, checkId: number, beforeId?: number) {
    return checked<CheckReviewPage>(await request(`/api/tasks/${taskId}/listings/${listingId}/checks/${checkId}/reviews?limit=20${beforeId ? `&before_id=${beforeId}` : ""}`),
      v => object(v) && Array.isArray(v.items) && v.items.length <= 20 && v.items.every(r => review(r, checkId)) &&
        (v.current_review === null || review(v.current_review, checkId)) && integer(v.latest_review_id) && integer(v.check_revision_id) &&
        typeof v.basis_token === "string" && /^[a-f0-9]{64}$/.test(v.basis_token) && integer(v.total_count) &&
        typeof v.has_more === "boolean" && (v.next_before_id === null || integer(v.next_before_id, 1)) && (!v.has_more || integer(v.next_before_id, 1)));
  },
  async changeCheckReview(taskId: number, listingId: number, checkId: number, change: CheckReviewChange) {
    return checked<CheckReview>(await request(`/api/tasks/${taskId}/listings/${listingId}/checks/${checkId}/reviews`, json(change)), v => review(v, checkId));
  },
  async getCheckSuggestions(taskId: number, listingId: number, beforeId?: number) {
    return checked<CheckSuggestionPage>(await request(`/api/tasks/${taskId}/listings/${listingId}/check-suggestions?limit=20${beforeId ? `&before_id=${beforeId}` : ""}`),
      v => object(v) && Array.isArray(v.items) && v.items.length <= 20 && v.items.every(s => object(s) &&
        integer(s.id, 1) && s.task_id === taskId && s.listing_id === listingId && integer(s.operation_id, 1) && integer(s.source_message_id, 1) &&
        typeof s.question === "string" && typeof s.reason === "string" && typeof s.created_at === "string" &&
        (s.check_id === null || integer(s.check_id, 1)) && textOrNull(s.accepted_at) && typeof s.stale === "boolean" && typeof s.reused_existing === "boolean") &&
        integer(v.total_count) && typeof v.has_more === "boolean" && (v.next_before_id === null || integer(v.next_before_id, 1)) && (!v.has_more || integer(v.next_before_id, 1)));
  },
  async acceptCheckSuggestion(taskId: number, listingId: number, suggestionId: number) {
    return checked<CheckSuggestionAcceptance>(await request(`/api/tasks/${taskId}/listings/${listingId}/check-suggestions/${suggestionId}/accept`, json({ confirm: true })),
      v => object(v) && v.suggestion_id === suggestionId && typeof v.reused_existing === "boolean" && item(v.check, taskId, listingId));
  },
  async getChecks(taskId: number, listingId: number, beforeId?: number) {
    return checked<CandidateCheckPage>(await request(`/api/tasks/${taskId}/listings/${listingId}/checks?limit=20${beforeId ? `&before_id=${beforeId}` : ""}`),
      v => object(v) && Array.isArray(v.items) && v.items.every(i => item(i, taskId, listingId)) && integer(v.total_count) &&
        object(v.counts) && ["pending", "evidence_linked", "dismissed"].every(k => integer((v.counts as Obj)[k])) &&
        typeof v.has_more === "boolean" && (v.next_before_id === null || integer(v.next_before_id, 1)) && (!v.has_more || integer(v.next_before_id, 1)) &&
        Array.isArray(v.available_statements) && v.available_statements.every(source) && integer(v.statement_count) && typeof v.statements_truncated === "boolean");
  },
  async createCheck(taskId: number, listingId: number, question: string, requestKey: string) {
    return checked<CandidateCheck>(await request(`/api/tasks/${taskId}/listings/${listingId}/checks`, json({ question, request_key: requestKey })),
      v => item(v, taskId, listingId));
  },
  async changeCheck(taskId: number, listingId: number, checkId: number, change: CheckChange) {
    return checked<CandidateCheck>(await request(`/api/tasks/${taskId}/listings/${listingId}/checks/${checkId}`, json(change, "PATCH")),
      v => item(v, taskId, listingId) && object(v) && v.id === checkId);
  },
};
