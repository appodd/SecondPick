import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { investigationApi, type Investigations as Data } from "../../api/investigationClient";
import { Investigations } from "./Investigations";
vi.mock("../../api/investigationClient", () => ({ investigationApi: { list: vi.fn(), plan: vi.fn(), act: vi.fn() } }));
afterEach(cleanup);
let state: Data;
beforeEach(() => { vi.resetAllMocks(); state = { items: [], skipped: [], automatic_research_held: false, max_listings: 3 }; vi.mocked(investigationApi.list).mockImplementation(async () => state); });
function show(listing?: number) { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Investigations id={3} listing={listing} /></QueryClientProvider>); }
function proposed(): Data { return { ...state, items: [{ id: 1, listing_id: 1879, goal_revision: 1, kind: "detail", state: "pending", outdated: false, job_id: null, job_state: null, stage: null, error_code: null,
  plan: { title: "隔离手柄", objective: "补充公开详情", reason: "历史提名且缺少描述", evidence_gaps: ["完整描述"], expected_information: ["完整描述"], capability: "BrowserJob 详情", manual_questions: ["能否提供漂移测试视频？"], seller_public_questions: [], source_study_ids: [49] }, outcome: {} }] }; }
it("reading never approves or executes; planning carries the listing scope", async () => {
  vi.mocked(investigationApi.plan).mockImplementation(async () => state = proposed()); show(1879);
  await userEvent.click(await screen.findByRole("button", { name: "整理本商品调查" }));
  expect(investigationApi.plan).toHaveBeenCalledWith(3, [1879]);
  expect(await screen.findByText("等待确认")).toBeVisible(); expect(investigationApi.act).not.toHaveBeenCalled();
});
it("approval and execution are separate; busy failure retains approved scope", async () => {
  state = proposed(); vi.mocked(investigationApi.act).mockImplementation(async (_,__, action) => {
    if (action === "execute") throw new Error("浏览器繁忙，本次未创建任务");
    state = { ...state, items: state.items.map(i => ({ ...i, state: "approved" })) }; return state;
  }); show();
  await userEvent.click(await screen.findByRole("button", { name: "批准本商品一次详情访问" }));
  expect(screen.getByText("已批准，尚未执行")).toBeVisible(); expect(investigationApi.act).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "确认执行（仅 1 件详情）" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("本次未创建任务"); expect(screen.getByText("已批准，尚未执行")).toBeVisible();
});
it("manual questions and stale goals never expose executable authorization", async () => {
  state = proposed(); state.items[0] = { ...state.items[0], kind: "manual", state: "manual", outdated: true }; show();
  expect(await screen.findByText("需要询问卖家或人工核实")).toBeVisible();
  expect(screen.queryByRole("button", { name: "批准本商品一次详情访问" })).toBeNull(); expect(screen.getByText(/目标已变化/)).toBeVisible();
});
