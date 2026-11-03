import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { CandidateCheck, CheckReview, CheckReviewPage } from "../../api/types";
import { CheckReviewPanel } from "./CheckReviewPanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const item: CandidateCheck = { id: 7, task_id: 1, listing_id: 2, question: "换过屏吗？", created_at: "fixture", revision_id: 0,
  state: "pending", effective_state: "pending", statement_id: null, statement_revision_id: null, statement_kind: null,
  statement_text: null, note: null, changed_at: null, evidence_current: false, needs_recheck: false };
const recorded: CheckReview = { id: 8, check_id: 7, check_revision_id: 0, action: "record", outcome: "answered", summary: "卖家称原装，仍待核对",
  sources: [{ statement_id: 9, revision_id: 3, kind: "seller_reply", statement_text: "卖家说全原", current: true }], status: "current", independently_verified: false, created_at: "fixture" };
const empty: CheckReviewPage = { items: [], current_review: null, latest_review_id: 0, check_revision_id: 0, basis_token: "a".repeat(64), total_count: 0, has_more: false, next_before_id: null };
function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <CheckReviewPanel item={item} sources={[{ id: 9, revision_id: 3, kind: "seller_reply", statement_text: "卖家说全原" }, { id: 10, revision_id: 0, kind: "user_observation", statement_text: "我看到维修记录" }]} />
  </QueryClientProvider>);
}
async function open() { await userEvent.click(screen.getByText("核实记录与来源", { exact: true })); }

it("loads lazily and saves the exact source and input versions", async () => {
  const get = vi.spyOn(api, "getCheckReviews").mockResolvedValueOnce(empty).mockResolvedValue({ ...empty, current_review: recorded, items: [recorded], latest_review_id: 8, total_count: 1 });
  const change = vi.spyOn(api, "changeCheckReview").mockResolvedValue(recorded);
  show(); expect(get).not.toHaveBeenCalled(); await open();
  await userEvent.type(await screen.findByRole("textbox", { name: "记录说明" }), "尚待核对");
  await userEvent.click(screen.getByRole("checkbox", { name: /卖家说全原/ }));
  await userEvent.click(screen.getByRole("button", { name: "保存用户核实记录" }));
  await waitFor(() => expect(change).toHaveBeenCalledWith(1, 2, 7, { action: "record", expected_review_id: 0, expected_check_revision_id: 0,
    expected_basis_token: "a".repeat(64), outcome: "uncertain", summary: "尚待核对", sources: [{ statement_id: 9, revision_id: 3 }] }));
  expect((await screen.findAllByText("用户记录：已有答复", { exact: true }))[0]).toBeVisible();
});

it("requires two source selections for conflict", async () => {
  vi.spyOn(api, "getCheckReviews").mockResolvedValue(empty); show(); await open();
  await userEvent.type(await screen.findByRole("textbox", { name: "记录说明" }), "两份记录不一致");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "用户记录状态" }), "conflict");
  await userEvent.click(screen.getAllByRole("checkbox")[0]);
  expect(screen.getByRole("button", { name: "保存用户核实记录" })).toBeDisabled();
  await userEvent.click(screen.getAllByRole("checkbox")[1]);
  expect(screen.getByRole("button", { name: "保存用户核实记录" })).toBeEnabled();
});

it("withdraws stale conclusions without copying them into a new record", async () => {
  vi.spyOn(api, "getCheckReviews").mockResolvedValue({ ...empty, current_review: { ...recorded, status: "needs_recheck" }, latest_review_id: 8 });
  const change = vi.spyOn(api, "changeCheckReview").mockResolvedValue({ ...recorded, action: "withdraw", outcome: null, summary: null, sources: [], status: "withdrawn" });
  show(); await open();
  expect(await screen.findByText(/来源、问题、要求或商品证据已变化/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "撤回本条核实记录" }));
  expect(change).toHaveBeenCalledWith(1, 2, 7, { action: "withdraw", expected_review_id: 8, expected_check_revision_id: 0, expected_basis_token: "a".repeat(64) });
});

it("retains a conflicting draft while refreshing versions", async () => {
  vi.spyOn(api, "getCheckReviews").mockResolvedValue(empty);
  vi.spyOn(api, "changeCheckReview").mockRejectedValue(new Error("记录已更新")); show(); await open();
  await userEvent.type(await screen.findByRole("textbox", { name: "记录说明" }), "保留草稿");
  await userEvent.click(screen.getAllByRole("checkbox")[0]);
  await userEvent.click(screen.getByRole("button", { name: "保存用户核实记录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("记录已更新");
  expect(screen.getByRole("textbox", { name: "记录说明" })).toHaveValue("保留草稿");
});
