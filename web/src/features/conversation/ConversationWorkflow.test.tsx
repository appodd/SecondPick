import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ConversationTimeline } from "./ConversationTimeline";
import { ActionRequestCard } from "./ActionRequestCard";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(node: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
}

it("enables a blank conversation and retains a failed draft", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "unavailable", message: "暂时无法发送" } }), { status: 503 })));
  mount(<ConversationTimeline />);
  await userEvent.type(screen.getByRole("textbox", { name: "对话输入" }), "找相机");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("暂时无法发送")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "对话输入" })).toHaveValue("找相机");
});

it("restores saved messages and an interrupted state", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.includes("/messages") ? { items: [{ id: 1, task_id: 8, role: "user", content: "相机需求", operation_id: 2, candidate_ids: [], created_at: "now" }], has_more: false, next_before_id: null } :
    url.includes("/operations") ? { operation: { id: 2, task_id: 8, state: "interrupted", error_code: "service_restarted", error_detail: "Service restarted" }, last_event_id: 4, action_request: null } :
    { items: [], has_more: false, next_before_id: null }
  ))));
  mount(<ConversationTimeline taskId={8} />);
  expect(await screen.findByText("相机需求")).toBeInTheDocument();
  expect(await screen.findByText(/服务重启，任务已中断/)).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
});

it("confirms only after the server response and makes non-execution explicit", async () => {
  const request = { id: 3, task_id: 8, operation_id: 2, summary: "补充搜索", risk: "将访问平台", listing_ids: [], actions: ["search" as const], state: "pending" as const };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ action_request: { ...request, state: "approved" }, operation: { id: 2, task_id: 8, state: "completed", error_code: null, error_detail: null } }))));
  mount(<ActionRequestCard request={request} />);
  expect(screen.getByText("确认仅记录请求；点击“执行采集”后才访问闲鱼")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
  expect(await screen.findByText("已确认，请核对执行范围")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认" })).not.toBeInTheDocument();
});

it("refreshes action history when an operation finishes before the event stream opens", async () => {
  const request = { id: 3, task_id: 8, operation_id: 2, summary: "快速完成的请求", risk: "访问平台", listing_ids: [], actions: ["search"], state: "pending" };
  let historyReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.includes("/messages") ? { items: [{ id: 1, task_id: 8, role: "user", content: "搜索", operation_id: 2, candidate_ids: [], created_at: "now" }], has_more: false, next_before_id: null } :
    url.includes("/operations") ? { operation: { id: 2, task_id: 8, state: "waiting_confirmation", error_code: null, error_detail: null }, last_event_id: 4, action_request: request } :
    { items: ++historyReads > 1 ? [request] : [], has_more: false, next_before_id: null }
  ))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["task", 8], { cached: "previous task snapshot" });
  render(<QueryClientProvider client={client}><MemoryRouter><ConversationTimeline taskId={8} /></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByRole("button", { name: "确认" })).toBeInTheDocument();
  await waitFor(() => expect(client.getQueryState(["task", 8])?.isInvalidated).toBe(true));
});

it("follows an accepted operation while a slow message refetch still shows the previous turn", async () => {
  let posted = false;
  const message = { id: 1, task_id: 8, role: "user", content: "先前消息", operation_id: 2, candidate_ids: [], created_at: "now" };
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes("/messages") && options?.method === "POST") {
      posted = true;
      return new Response(JSON.stringify({ message: { ...message, id: 2, operation_id: 3, content: "下一轮" },
        operation: { id: 3, task_id: 8, state: "queued", error_code: null, error_detail: null } }), { status: 202 });
    }
    if (url.includes("/messages") && posted) return new Promise<Response>(() => {});
    return new Response(JSON.stringify(url.includes("/messages") ? { items: [message], has_more: false, next_before_id: null } :
      url.includes("/operations") ? { operation: { id: posted ? 3 : 2, task_id: 8, state: posted ? "queued" : "completed", error_code: null, error_detail: null }, last_event_id: 0, action_request: null } :
      { items: [], has_more: false, next_before_id: null }));
  }));
  mount(<ConversationTimeline taskId={8} />);
  expect(await screen.findByText("本次分析已完成")).toBeInTheDocument();
  await userEvent.type(screen.getByRole("textbox", { name: "对话输入" }), "下一轮");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByRole("button", { name: "停止" })).toBeVisible();
  expect(screen.queryByText("本次分析已完成")).not.toBeInTheDocument();
  expect(screen.getByText("先前消息")).toBeInTheDocument();
});
