import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { monitorApi, type Monitor } from "../../api/monitorClient";
import { MonitorConsole } from "./MonitorConsole";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const monitor = { id: 1, task_id: 16, state: "running" } as Monitor;
function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MonitorConsole monitor={monitor} /></QueryClientProvider>);
}
const page = { items: [{ at: "2026-10-20T09:00:00Z", text: "page 1: waiting 5 seconds" }],
  rounds: [{ id: "a".repeat(32), updated_at: "2026-10-20T09:00:00Z" }], round_id: "a".repeat(32),
  next_before: 100, has_more: true, capture_enabled: true, max_bytes: 4194304, max_rounds: 5 };

it("shows output as literal text and browses earlier history without mixing pages", async () => {
  const logs = vi.spyOn(monitorApi, "logs").mockImplementation(async (_task, _id, _round, before) => before === undefined
    ? { ...page, items: [...page.items, { at: page.items[0].at, text: '<script>alert("unsafe")</script>' }] }
    : { ...page, items: [{ at: page.items[0].at, text: "older output" }], next_before: null, has_more: false });
  mount();
  expect(await screen.findByRole("log")).toHaveTextContent("page 1: waiting 5 seconds");
  expect(screen.getByRole("log").querySelector("script")).toBeNull();
  expect(screen.getByRole("log")).toHaveTextContent('<script>alert("unsafe")</script>');
  await userEvent.click(screen.getByRole("button", { name: "查看更早日志" }));
  await waitFor(() => expect(screen.getByRole("log")).toHaveTextContent("older output"));
  expect(logs).toHaveBeenCalledWith(16, 1, "a".repeat(32), 100);
  expect(screen.getByText(/正在查看历史片段/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "回到最新日志" }));
  await waitFor(() => expect(screen.getByRole("log")).toHaveTextContent("page 1"));
});

it("explains old output cannot be recovered without starting another round", async () => {
  const logs = vi.spyOn(monitorApi, "logs").mockResolvedValue({ ...page, items: [], rounds: [], round_id: null, has_more: false });
  mount();
  expect(await screen.findByText(/以前未保存的输出无法补回/)).toBeVisible();
  expect(logs).toHaveBeenCalledWith(16, 1, undefined, undefined);
});

it("displays fetch failures and supports manual refresh", async () => {
  const logs = vi.spyOn(monitorApi, "logs").mockRejectedValueOnce(new Error("日志读取失败")).mockResolvedValue(page);
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("日志读取失败");
  await userEvent.click(screen.getByRole("button", { name: "刷新日志" }));
  expect(await screen.findByRole("log")).toHaveTextContent("page 1");
  expect(logs).toHaveBeenCalledTimes(2);
});

it("switches actual log round IDs, reports historical mode and restores latest output", async () => {
  const older = "b".repeat(32);
  const logs = vi.spyOn(monitorApi, "logs").mockImplementation(async (_task, _id, selected) => ({ ...page,
    rounds: [...page.rounds, { id: older, updated_at: "2026-10-19T09:00:00Z" }], round_id: selected || page.round_id,
    items: [{ at: page.items[0].at, text: selected === older ? "historical round" : "latest round" }] }));
  mount();
  expect(await screen.findByRole("log")).toHaveTextContent("latest round");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "日志采集轮次" }), older);
  await waitFor(() => expect(screen.getByRole("log")).toHaveTextContent("historical round"));
  expect(logs).toHaveBeenLastCalledWith(16, 1, older, undefined);
  expect(screen.getByText(/指定历史轮次，自动刷新已暂停/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "回到最新日志" }));
  await waitFor(() => expect(screen.getByRole("log")).toHaveTextContent("latest round"));
});
