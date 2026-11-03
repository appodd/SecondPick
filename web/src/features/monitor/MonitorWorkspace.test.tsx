import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { MonitorWorkspace, useMonitors } from "./MonitorWorkspace";
import type { Monitor } from "../../api/monitorClient";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const monitor: Monitor = { id: 1, task_id: 8, keyword: "NS2 Pro", max_pages: 10, max_items: 100,
  max_rounds: 24, interval_seconds: 1800, collect_seller_profiles: false, rounds: 1, imported: 2,
  state: "paused", desired_state: null, error_code: "service_restarted", next_run_at: null, updated_at: "now",
  result: { imported: 2, search_cards: { imported: 405 }, price_observations: { imported: 405 } } };
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Workspace() { return <MonitorWorkspace taskId={8} query={useMonitors(8)} />; }
  render(<QueryClientProvider client={client}><MemoryRouter><Workspace /></MemoryRouter></QueryClientProvider>);
  return client;
}
function mock(items: Monitor[] = [], enabled = true) {
  let current = items;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/monitor-engine/check") return Response.json(init?.method === "POST"
      ? { ready: false, checked_at: "now", checks: [{ code: "dependencies", ok: false }] } : { result: null });
    if (url.includes("/events")) return Response.json({ items: [{ id: 1, phase: "finished", code: "engine_timeout", created_at: "2026-10-20T09:00:00Z", counts: { imported: 2 } }], has_more: false, next_before_id: null });
    if (init?.method === "POST") {
      if (url.endsWith("/resume")) current = [{ ...monitor, state: "waiting", error_code: null }];
      else if (url.endsWith("/stop")) current = [{ ...current[0], state: "stopped" }];
      else current = [{ ...monitor, ...JSON.parse(String(init.body)), state: "waiting" }];
      return Response.json(current[0]);
    }
    return Response.json({ enabled, platform_enabled: true, candidate_pool_count: items.length ? 405 : 0, items: current });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

it("does not allow disabled monitoring to create a scope", async () => {
  const fetcher = mock([], false); mount();
  expect(await screen.findByText(/当前服务未启用监控/)).toBeVisible();
  expect(screen.getByRole("button", { name: "确认范围并启动监控" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "监控关键词" })).toBeEnabled();
  await userEvent.type(screen.getByRole("textbox", { name: "监控关键词" }), "Switch 2 Pro 手柄");
  await userEvent.click(screen.getByRole("checkbox", { name: /我已确认以上范围/ }));
  expect(screen.getByRole("button", { name: "确认范围并启动监控" })).toBeDisabled();
  expect(fetcher.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
});

it("requires scope confirmation, clears it when changed, and posts bounded permissions", async () => {
  const fetcher = mock(); mount();
  await screen.findByText("暂无监控，确认范围后开始积累商品。");
  await userEvent.type(screen.getByRole("textbox", { name: "监控关键词" }), "NS2 Pro");
  const start = screen.getByRole("button", { name: "确认范围并启动监控" });
  const ack = screen.getByRole("checkbox", { name: /我已确认以上范围/ });
  expect(start).toBeDisabled();
  await userEvent.click(ack);
  await userEvent.click(screen.getByRole("checkbox", { name: /允许访问卖家主页/ }));
  expect(ack).not.toBeChecked(); expect(start).toBeDisabled();
  await userEvent.click(ack); await userEvent.click(start);
  await screen.findByRole("article", { name: "监控 NS2 Pro #1" });
  const posted = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(String(posted[1]?.body))).toEqual({ keyword: "NS2 Pro", max_pages: 10, max_items: 100,
    interval_seconds: 1800, max_rounds: 24, collect_seller_profiles: true, confirmed: true });
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("shows a unique pool separately from records and resumes without reconfirmation", async () => {
  const fetcher = mock([monitor]); mount();
  const card = await screen.findByRole("article", { name: "监控 NS2 Pro #1" });
  expect(screen.getByText("当前任务去重候选（含已有数据）").parentElement).toHaveTextContent("405");
  expect(within(card).getByText(/服务已重启/)).toBeVisible();
  expect(within(card).getByText(/不相加作为候选数量/)).toBeVisible();
  await userEvent.click(within(card).getByRole("button", { name: "恢复原范围" }));
  expect(await within(card).findByText("等待下一轮")).toBeVisible();
  expect(fetcher.mock.calls.find(([url]) => url.endsWith("/resume"))?.[1]?.body).toBeUndefined();
  await userEvent.click(within(card).getByRole("button", { name: "停止监控（含当前采集）" }));
  expect(await within(card).findByText("监控已停止")).toBeVisible();
  expect(within(card).queryByRole("button", { name: "恢复原范围" })).toBeNull();
});

it("retains live numbers while stopping and explains incomplete sync and diagnostics", async () => {
  mock([{ ...monitor, state: "running", desired_state: "paused", error_code: null,
    result: { ...monitor.result, sync_pending: true, diagnostics_available: false } }]); mount();
  const card = await screen.findByRole("article", { name: "监控 NS2 Pro #1" });
  expect(within(card).getByText("正在暂停采集并保存数据")).toBeVisible();
  expect(within(card).getByRole("button", { name: "暂停监控（含当前采集）" })).toBeDisabled();
  expect(within(card).getByText(/还有记录待同步/)).toBeVisible();
  await userEvent.click(within(card).getByRole("button", { name: "查看运行记录" }));
  expect(await within(card).findByText(/本轮采集超时/)).toBeVisible();
});

it("continues a stopped monitor only on click without creating another scope", async () => {
  const fetcher = mock([{ ...monitor, state: "stopped", error_code: "cancelled" }]); mount();
  const card = await screen.findByRole("article", { name: "监控 NS2 Pro #1" });
  expect(within(card).getByText(/还剩 23 轮/)).toBeVisible();
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  await userEvent.click(within(card).getByRole("button", { name: "继续原监控" }));
  expect(await within(card).findByText("等待下一轮")).toBeVisible();
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/api/tasks/8/monitors/1/resume");
});

it("keeps cumulative records visible when a later attempt fails before collection", async () => {
  mock([{ ...monitor, state: "needs_attention", rounds: 3, imported: 169,
    error_code: "login_required", result: { imported: 0 } }]); mount();
  const card = await screen.findByRole("article", { name: "监控 NS2 Pro #1" });
  expect(within(card).getByLabelText("累计保留的数据")).toHaveTextContent("本监控累计商品记录169");
  expect(within(card).getByLabelText("累计保留的数据")).toHaveTextContent("当前任务去重候选（含其他来源）405");
  expect(within(card).getByText(/已尝试 3 \/ 24 轮 · 剩余 21 轮/)).toBeVisible();
  expect(within(card).getByText(/尝试次数包含登录失败/)).toBeVisible();
  expect(within(card).getByLabelText("最近一轮同步记录")).toHaveTextContent("商品记录0搜索卡片—报价观察—");
  expect(within(card).getByText(/0 不代表历史数据清零/)).toBeVisible();
});

it("does not offer continuation when the original round budget is exhausted", async () => {
  mock([{ ...monitor, state: "stopped", rounds: 24 }]); mount();
  const card = await screen.findByRole("article", { name: "监控 NS2 Pro #1" });
  expect(within(card).queryByRole("button", { name: "继续原监控" })).toBeNull();
  expect(within(card).getByText(/已用完确认的轮次/)).toBeVisible();
});

it("disables stopped monitor continuation when the engine is disabled", async () => {
  const fetcher = mock([{ ...monitor, state: "stopped" }], false); mount();
  expect(await screen.findByRole("button", { name: "继续原监控" })).toBeDisabled();
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});

it("keeps saved data and disables creation when status refresh fails", async () => {
  const fetcher = mock([monitor]); const client = mount();
  await screen.findByRole("article");
  fetcher.mockRejectedValue(new Error("网络断开"));
  await client.invalidateQueries({ queryKey: ["monitors", 8] });
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("网络断开"));
  expect(screen.getByRole("article")).toBeVisible();
  expect(screen.getByRole("button", { name: "恢复原范围" })).toBeDisabled();
});

it("refreshes candidate evidence when details arrive without growing the unique pool", async () => {
  mock([monitor]); const client = mount();
  await screen.findByRole("article");
  client.setQueryData(["task", 8, "candidate-pages", 50], { cached: true });
  client.setQueryData(["monitors", 8], { enabled: true, platform_enabled: true, candidate_pool_count: 405,
    items: [{ ...monitor, result: { ...monitor.result, imported: 3 } }] });
  await waitFor(() => expect(client.getQueryState(["task", 8, "candidate-pages", 50])?.isInvalidated).toBe(true));
});

it("checks environment explicitly and prevents start after a failed check", async () => {
  const fetcher = mock(); mount();
  await screen.findByText("暂无监控，确认范围后开始积累商品。");
  await userEvent.type(screen.getByRole("textbox", { name: "监控关键词" }), "手柄");
  await userEvent.click(screen.getByRole("checkbox", { name: /我已确认以上范围/ }));
  expect(screen.getByRole("button", { name: "确认范围并启动监控" })).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "检查采集环境" }));
  expect(await screen.findByText("采集依赖：未通过")).toBeVisible();
  expect(screen.getByRole("button", { name: "确认范围并启动监控" })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([url, init]) => url === "/api/tasks/8/monitors" && init?.method === "POST")).toHaveLength(0);
});
