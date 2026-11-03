import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { CandidateCheck, CandidateCheckPage } from "../../api/types";
import { CandidateChecks } from "./CandidateChecks";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => { vi.spyOn(api, "getCheckSuggestions").mockResolvedValue({ items: [], total_count: 0, has_more: false, next_before_id: null }); });
const item: CandidateCheck = { id: 7, task_id: 1, listing_id: 2, question: "屏幕是否换过？", created_at: "fixture",
  revision_id: 0, state: "pending", effective_state: "pending", statement_id: null, statement_revision_id: null,
  statement_kind: null, statement_text: null, note: null, changed_at: null, evidence_current: false, needs_recheck: false };
const page: CandidateCheckPage = { items: [item], total_count: 1, counts: { pending: 1, evidence_linked: 0, dismissed: 0 },
  has_more: false, next_before_id: null, available_statements: [{ id: 9, revision_id: 4, kind: "seller_reply", statement_text: "卖家原话：没换过屏" }],
  statement_count: 1, statements_truncated: false };
function renderChecks() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><CandidateChecks taskId={1} listingId={2} /></QueryClientProvider>);
  return client;
}
async function open() {
  await userEvent.click(screen.getByText("待核实清单", { exact: true }));
  await screen.findByRole("button", { name: "保存问题" });
}

it("loads only when opened and retains a failed question without sending a message", async () => {
  const get = vi.spyOn(api, "getChecks").mockResolvedValue({ ...page, items: [] });
  const create = vi.spyOn(api, "createCheck").mockRejectedValue(new Error("保存失败"));
  const send = vi.spyOn(api, "sendMessage");
  renderChecks();
  expect(get).not.toHaveBeenCalled();
  await open();
  await userEvent.type(screen.getByRole("textbox", { name: "新增核实问题" }), "容量是否同机？");
  await userEvent.click(screen.getByRole("button", { name: "保存问题" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
  expect(screen.getByRole("textbox", { name: "新增核实问题" })).toHaveValue("容量是否同机？");
  expect(create).toHaveBeenCalledWith(1, 2, "容量是否同机？", expect.any(String));
  expect(send).not.toHaveBeenCalled();
});

it("links the selected statement version with a note without certifying it", async () => {
  vi.spyOn(api, "getChecks").mockResolvedValue(page);
  const change = vi.spyOn(api, "changeCheck").mockResolvedValue(item);
  renderChecks();
  await open();
  await screen.findByText("屏幕是否换过？");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "关联当前补充" }), "9");
  await userEvent.type(screen.getByRole("textbox", { name: "核实备注" }), "面交还要核对");
  await userEvent.click(screen.getByRole("button", { name: /^关联补充$/ }));
  await waitFor(() => expect(change).toHaveBeenCalledWith(1, 2, 7, { expected_revision_id: 0, state: "evidence_linked",
    statement_id: 9, statement_revision_id: 4, note: "面交还要核对" }));
  expect(screen.getByText("已保存；补充仍需核实。")).toBeVisible();
});

it("shows stale linkage and allows reopening instead of showing verified", async () => {
  vi.spyOn(api, "getChecks").mockResolvedValue({ ...page, items: [{ ...item, state: "evidence_linked", revision_id: 3,
    statement_id: 9, statement_revision_id: 0, statement_kind: "seller_reply", statement_text: "旧原文", needs_recheck: true }], available_statements: [] });
  const change = vi.spyOn(api, "changeCheck").mockResolvedValue(item);
  renderChecks();
  await open();
  expect(await screen.findByText(/关联补充已撤回/)).toBeVisible();
  await userEvent.click(screen.getByText("查看当时关联的原文", { exact: true }));
  expect(screen.getByText("用户转述卖家答复 · 未经独立核实")).toBeVisible();
  expect(screen.getByText("旧原文")).toBeVisible();
  expect(screen.getByRole("button", { name: /^关联补充$/ })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "重新核实" }));
  expect(change).toHaveBeenCalledWith(1, 2, 7, { state: "pending", expected_revision_id: 3 });
});

it("retains notes after a version conflict and refreshes source choices", async () => {
  vi.spyOn(api, "getChecks").mockResolvedValueOnce(page).mockResolvedValue({ ...page, available_statements: [] });
  vi.spyOn(api, "changeCheck").mockRejectedValue(new Error("事项已更新"));
  renderChecks();
  await open();
  await screen.findByText("屏幕是否换过？");
  await userEvent.type(screen.getByRole("textbox", { name: "核实备注" }), "保留草稿");
  await userEvent.click(screen.getByRole("button", { name: "暂不跟进此项" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("事项已更新");
  expect(screen.getByRole("textbox", { name: "核实备注" })).toHaveValue("保留草稿");
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(1));
});

it("loads older questions while keeping the first page", async () => {
  const get = vi.spyOn(api, "getChecks").mockResolvedValueOnce({ ...page, has_more: true, next_before_id: 7 })
    .mockResolvedValue({ ...page, items: [{ ...item, id: 6, question: "更早的问题" }] });
  renderChecks();
  await open();
  await userEvent.click(await screen.findByRole("button", { name: "加载更早核实事项" }));
  expect(await screen.findByText("更早的问题")).toBeVisible();
  expect(screen.getByText("屏幕是否换过？")).toBeVisible();
  expect(get).toHaveBeenLastCalledWith(1, 2, 7);
});
