import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { TaskHeader } from "./TaskHeader";
import type { TaskDetail } from "../../api/types";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const fixtureTask = { id: 1, title: "Original", goal: "Goal", original_goal: "Goal", effective_goal: "Goal", city: "上海", status: "active", notes: null, created_at: "now", updated_at: "now" };
function mountHeader() {
  const detail = { task: fixtureTask, reports: [], search_coverage: { status: "collecting" } } as unknown as TaskDetail;
  return render(<QueryClientProvider client={new QueryClient()}><TaskHeader taskDetail={detail} /><button>其他地方</button></QueryClientProvider>);
}
it("renames the title without changing the goal", async () => {
  const task = { id: 1, title: "Original", goal: "Goal", original_goal: "Goal", effective_goal: "Goal", city: "上海", status: "active", notes: null, created_at: "now", updated_at: "now" };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...task, title: "Camera" }))));
  const detail = { task, reports: [], search_coverage: { status: "collecting" } } as unknown as TaskDetail;
  render(<QueryClientProvider client={new QueryClient()}><TaskHeader taskDetail={detail} /></QueryClientProvider>);
  await userEvent.click(screen.getByRole("button", { name: "重命名任务" }));
  const input = screen.getByRole("textbox", { name: "任务名称" });
  await userEvent.clear(input);
  await userEvent.type(input, "Camera");
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("heading", { name: "Camera" })).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith("/api/tasks/1", expect.objectContaining({ body: '{"title":"Camera"}', method: "PATCH" }));
});

it("saves changes once when focus leaves the editor and reopens the saved title", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ...fixtureTask, title: "Camera" })));
  vi.stubGlobal("fetch", fetchMock);
  mountHeader();
  await userEvent.click(screen.getByRole("button", { name: "重命名任务" }));
  await userEvent.clear(screen.getByRole("textbox", { name: "任务名称" }));
  await userEvent.type(screen.getByRole("textbox", { name: "任务名称" }), "Camera");
  await userEvent.click(screen.getByRole("button", { name: "其他地方" }));
  expect(await screen.findByRole("heading", { name: "Camera" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "重命名任务" }));
  expect(screen.getByRole("textbox", { name: "任务名称" })).toHaveValue("Camera");
});

it("closes unchanged edits without sending a request", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  mountHeader();
  await userEvent.click(screen.getByRole("button", { name: "重命名任务" }));
  await userEvent.click(screen.getByRole("button", { name: "其他地方" }));
  expect(screen.queryByRole("textbox", { name: "任务名称" })).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("Escape cancels a changed draft without autosaving", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  mountHeader();
  await userEvent.click(screen.getByRole("button", { name: "重命名任务" }));
  await userEvent.type(screen.getByRole("textbox", { name: "任务名称" }), " changed");
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("heading", { name: "Original" })).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("keeps a failed autosave draft and permits retry", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { code: "unavailable", message: "暂时无法保存" } }), { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  mountHeader();
  await userEvent.click(screen.getByRole("button", { name: "重命名任务" }));
  await userEvent.clear(screen.getByRole("textbox", { name: "任务名称" }));
  await userEvent.type(screen.getByRole("textbox", { name: "任务名称" }), "Camera");
  await userEvent.click(screen.getByRole("button", { name: "其他地方" }));
  expect(await screen.findByText("暂时无法保存")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "任务名称" })).toHaveValue("Camera");
  expect(screen.getByRole("button", { name: "保存" })).toBeEnabled();
});
