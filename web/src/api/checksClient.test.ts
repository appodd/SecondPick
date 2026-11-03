import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());
const item = { id: 7, task_id: 1, listing_id: 2, question: "原装情况？", created_at: "fixture", revision_id: 0,
  state: "pending", effective_state: "pending", statement_id: null, statement_revision_id: null,
  statement_kind: null, statement_text: null, note: null, changed_at: null, evidence_current: false, needs_recheck: false };
const page = { items: [item], total_count: 1, counts: { pending: 1, evidence_linked: 0, dismissed: 0 },
  has_more: false, next_before_id: null, available_statements: [{ id: 9, revision_id: 0, kind: "seller_reply", statement_text: "原话" }],
  statement_count: 1, statements_truncated: false };
function respond(body: unknown) {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

it("retains zero source revision and bounded page metadata", async () => {
  respond(page);
  expect(await api.getChecks(1, 2)).toEqual(page);
});

it.each(["foreign_scope", "missing_revision"])("rejects %s transport data", async fault => {
  respond(fault === "foreign_scope" ? { ...page, items: [{ ...item, task_id: 3 }] } :
    { ...page, available_statements: [{ id: 9, kind: "seller_reply", statement_text: "原话" }] });
  await expect(api.getChecks(1, 2)).rejects.toMatchObject({ code: "invalid_response" });
});

it("sends both optimistic versions without launching a conversation", async () => {
  const fetcher = respond(item);
  const change = { state: "evidence_linked" as const, expected_revision_id: 0, statement_id: 9, statement_revision_id: 4 };
  await api.changeCheck(1, 2, 7, change);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/tasks/1/listings/2/checks/7");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(change);
});

it("requires explicit suggestion confirmation and validates its scope", async () => {
  const fetcher = respond({ suggestion_id: 8, check: item, reused_existing: true });
  await api.acceptCheckSuggestion(1, 2, 8);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ confirm: true });
  expect(fetcher.mock.calls[0][0]).toBe("/api/tasks/1/listings/2/check-suggestions/8/accept");
  respond({ suggestion_id: 8, check: { ...item, listing_id: 3 }, reused_existing: true });
  await expect(api.acceptCheckSuggestion(1, 2, 8)).rejects.toMatchObject({ code: "invalid_response" });
});

it("rejects unscoped or incomplete suggestions", async () => {
  respond({ items: [{ id: 8, task_id: 9, listing_id: 2 }], total_count: 1, has_more: false, next_before_id: null });
  await expect(api.getCheckSuggestions(1, 2)).rejects.toMatchObject({ code: "invalid_response" });
});

it("rejects review data that claims independent verification or another question", async () => {
  const value = { id: 1, check_id: 7, check_revision_id: 0, action: "record", outcome: "answered", summary: "记录", created_at: "fixture", sources: [], status: "current", independently_verified: true };
  respond(value);
  await expect(api.changeCheckReview(1, 2, 7, { action: "withdraw", expected_review_id: 0, expected_check_revision_id: 0, expected_basis_token: "a".repeat(64) })).rejects.toMatchObject({ code: "invalid_response" });
  respond({ ...value, check_id: 9, independently_verified: false });
  await expect(api.changeCheckReview(1, 2, 7, { action: "withdraw", expected_review_id: 0, expected_check_revision_id: 0, expected_basis_token: "a".repeat(64) })).rejects.toMatchObject({ code: "invalid_response" });
});
