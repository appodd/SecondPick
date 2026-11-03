import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { CandidateCheck, CheckSuggestionRecord } from "../../api/types";
import { SuggestedChecks } from "./SuggestedChecks";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const suggestion: CheckSuggestionRecord = { id: 5, task_id: 1, listing_id: 2, operation_id: 3, source_message_id: 4,
  question: "能否核对维修记录？", reason: "维修史未知", created_at: "fixture", check_id: null, accepted_at: null, reused_existing: false, stale: false };
const check: CandidateCheck = { id: 7, task_id: 1, listing_id: 2, question: suggestion.question, created_at: "fixture", revision_id: 0,
  state: "pending", effective_state: "pending", statement_id: null, statement_revision_id: null, statement_kind: null,
  statement_text: null, note: null, changed_at: null, evidence_current: false, needs_recheck: false };
const page = { items: [suggestion], total_count: 1, has_more: false, next_before_id: null };
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><SuggestedChecks taskId={1} listingId={2} /></QueryClientProvider>);
}

it("requires a click before saving and refreshes both lists", async () => {
  vi.spyOn(api, "getCheckSuggestions").mockResolvedValueOnce(page).mockResolvedValue({ ...page, items: [{ ...suggestion, check_id: 7, accepted_at: "now" }] });
  const save = vi.spyOn(api, "acceptCheckSuggestion").mockResolvedValue({ suggestion_id: 5, check, reused_existing: false });
  const send = vi.spyOn(api, "sendMessage");
  show();
  const button = await screen.findByRole("button", { name: "确认保存此问题" });
  expect(save).not.toHaveBeenCalled();
  await userEvent.click(button);
  expect(await screen.findByText("已加入清单，仍需核实")).toBeVisible();
  expect(screen.getByText("未确认的建议不会加入清单。核对问题后逐项确认；保存不会联系卖家、分析商品或表示核实通过。")).toBeVisible();
  expect(save).toHaveBeenCalledWith(1, 2, 5);
  expect(send).not.toHaveBeenCalled();
});

it("keeps dismissed duplicates dismissed and explains reuse", async () => {
  vi.spyOn(api, "getCheckSuggestions").mockResolvedValue(page);
  vi.spyOn(api, "acceptCheckSuggestion").mockResolvedValue({ suggestion_id: 5, check: { ...check, state: "dismissed", effective_state: "dismissed" }, reused_existing: true });
  show();
  await userEvent.click(await screen.findByRole("button", { name: "确认保存此问题" }));
  expect(await screen.findByText("已有相同问题且已暂不跟进；保留原状态，未重新打开。")).toBeVisible();
});

it("disables stale suggestions and retains a failed confirmation", async () => {
  vi.spyOn(api, "getCheckSuggestions").mockResolvedValueOnce(page).mockResolvedValue({ ...page, items: [{ ...suggestion, stale: true }] });
  vi.spyOn(api, "acceptCheckSuggestion").mockRejectedValue(new Error("证据已经变化"));
  show();
  await userEvent.click(await screen.findByRole("button", { name: "确认保存此问题" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("证据已经变化");
  expect(await screen.findByText(/建议依据的要求或证据已变化/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "确认保存此问题" })).toBeNull();
});

it("loads older suggestions without replacing the current page", async () => {
  const get = vi.spyOn(api, "getCheckSuggestions").mockResolvedValueOnce({ ...page, has_more: true, next_before_id: 5 })
    .mockResolvedValue({ ...page, items: [{ ...suggestion, id: 4, question: "更早的问题" }] });
  show();
  await userEvent.click(await screen.findByRole("button", { name: "加载更早建议" }));
  expect(await screen.findByText("更早的问题")).toBeVisible();
  expect(screen.getByText(suggestion.question)).toBeVisible();
  await waitFor(() => expect(get).toHaveBeenLastCalledWith(1, 2, 5));
});
