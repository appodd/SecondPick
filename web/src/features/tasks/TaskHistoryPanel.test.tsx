import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { TaskDetail, TaskHistory } from "../../api/types";
import { TaskHistoryPanel } from "./TaskHistoryPanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const revision = (id: number) => ({ id, task_id: 1, user_message: `修订消息${id}`, effective_goal: `目标${id}`, added_preferences: [], removed_preferences: [], created_at: "fixture" });
const task: TaskDetail = {
  task: { id: 1, title: "任务", goal: "原始", original_goal: "原始", effective_goal: "最新", city: "上海", status: "active", notes: null, created_at: "fixture", updated_at: "fixture" },
  preference_revisions: [revision(2)], runs: [], reports: [],
  search_coverage: { status: "collecting", unique_candidates: 0, target_min: 300, target_max: 600, marginal_gain_threshold: 0.1, low_gain_streak: 0, suggested_action: "continue_search", runs: [] },
  history_page: { limit: 10, has_more: true, next_cursor: "older", total_counts: { preference_revisions: 2, runs: 0, reports: 0 } },
};
const older: TaskHistory = { ...task, preference_revisions: [revision(1), revision(2)], history_page: { ...task.history_page!, has_more: false, next_cursor: null } };

function show(value = task) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><TaskHistoryPanel task={value} /></QueryClientProvider>);
}

it("loads metadata only on request, deduplicates and retains earlier records", async () => {
  const load = vi.spyOn(api, "getTaskHistory").mockResolvedValue(older);
  show();
  expect(load).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("查看任务记录（需求修订、采集轮次与报告）"));
  expect(screen.getByRole("status")).toHaveTextContent("需求修订 1/2");
  await userEvent.click(screen.getByRole("button", { name: "加载更早任务记录" }));
  expect(await screen.findByText("修订消息1")).toBeVisible();
  expect(screen.getAllByText("修订消息2")).toHaveLength(1);
  expect(screen.getByRole("status")).toHaveTextContent("需求修订 2/2");
  expect(screen.queryByRole("button", { name: "加载更早任务记录" })).not.toBeInTheDocument();
  expect(load).toHaveBeenCalledWith(1, "older");
});

it("retains the first page after a failed read and supports an explicit retry", async () => {
  vi.spyOn(api, "getTaskHistory").mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(older);
  show();
  await userEvent.click(screen.getByText("查看任务记录（需求修订、采集轮次与报告）"));
  await userEvent.click(screen.getByRole("button", { name: "加载更早任务记录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("可重试加载");
  expect(screen.getByText("修订消息2")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "加载更早任务记录" }));
  expect(await screen.findByText("修订消息1")).toBeVisible();
});

it("retains compatibility with task responses without pagination metadata", () => {
  const load = vi.spyOn(api, "getTaskHistory");
  show({ ...task, history_page: undefined });
  expect(screen.queryByText("查看任务记录（需求修订、采集轮次与报告）")).not.toBeInTheDocument();
  expect(load).not.toHaveBeenCalled();
});

it("retries the failed later cursor without restarting already loaded pages", async () => {
  const initial = { ...task, preference_revisions: [revision(3)], history_page: {
    ...task.history_page!, total_counts: { preference_revisions: 3, runs: 0, reports: 0 } } };
  const load = vi.spyOn(api, "getTaskHistory")
    .mockResolvedValueOnce({ ...older, preference_revisions: [revision(2)], history_page: {
      ...initial.history_page, next_cursor: "oldest", has_more: true } })
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...older, preference_revisions: [revision(1)] });
  show(initial);
  await userEvent.click(screen.getByText("查看任务记录（需求修订、采集轮次与报告）"));
  await userEvent.click(screen.getByRole("button", { name: "加载更早任务记录" }));
  expect(await screen.findByText("修订消息2")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "加载更早任务记录" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByText("修订消息2")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "加载更早任务记录" }));
  expect(await screen.findByText("修订消息1")).toBeVisible();
  expect(load.mock.calls.map(call => call[1])).toEqual(["older", "oldest", "oldest"]);
});
