import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProjectCreator } from "./ProjectCreator";
import { MonitorCreator } from "./MonitorCreator";
import { projectApi, type ProjectDraft } from "../../api/projectClient";

vi.mock("../../api/projectClient", () => ({ projectApi: { draft: vi.fn(), create: vi.fn(), monitorDraft: vi.fn() } }));
const response: ProjectDraft = { title: "AI 项目", goal: "服务器整理的目标", budget: 6000, hard: ["16GB 内存"], soft: ["优先原装"], minimum: 30, auto_research: true };
function pending() { let resolve!: (value: ProjectDraft) => void; const promise = new Promise<ProjectDraft>(done => { resolve = done; }); vi.mocked(projectApi.draft).mockReturnValue(promise); return resolve; }
function show() { const created = vi.fn().mockResolvedValue(undefined); const view = render(<ProjectCreator close={vi.fn()} created={created} />); fireEvent.change(screen.getByLabelText("选购目标"), { target: { value: "选一台 MacBook" } }); return { ...view, created }; }
beforeEach(() => vi.resetAllMocks());
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('explains the project once and gives a concrete input example without calling AI',()=>{render(<ProjectCreator close={vi.fn()} created={vi.fn()}/>);expect(screen.getAllByRole('heading',{name:'新建选购项目'})).toHaveLength(1);expect(screen.getByText('围绕一个购买目标，持续收集商品、比较候选并更新选购建议。')).toBeVisible();expect(screen.getByLabelText('选购目标')).toHaveAttribute('placeholder',expect.stringContaining('预算 400 元'));expect(screen.queryByText('输入目标，AI 整理需求后可编辑确认。也可以手动填写。')).toBeNull();expect(projectApi.draft).not.toHaveBeenCalled()});

it("fills structured fields while preserving the submitted goal and user-owned research settings", async () => {
  const resolve = pending(); show();
  fireEvent.change(screen.getByLabelText("首轮初步样本门槛"), { target: { value: "45" } });
  fireEvent.click(screen.getByRole("button", { name: "AI 解析需求" }));
  await act(async () => resolve(response));
  expect(screen.getByLabelText("项目名称")).toHaveValue("AI 项目");
  expect(screen.getByLabelText("选购目标")).toHaveValue("选一台 MacBook");
  expect(screen.getByLabelText("预算上限（元）")).toHaveValue(6000);
  expect(screen.getByLabelText("首轮初步样本门槛")).toHaveValue(45);
  expect(screen.getByRole("checkbox", { name: /授权自动批次研究/ })).not.toBeChecked();
  expect(screen.getByLabelText("已整理的选购条件")).toHaveTextContent("16GB 内存");
  expect(projectApi.create).not.toHaveBeenCalled();
});

it("keeps every field edited during a request, including values changed back", async () => {
  const resolve = pending(); show();
  fireEvent.click(screen.getByRole("button", { name: "AI 解析需求" }));
  fireEvent.change(screen.getByLabelText("预算上限（元）"), { target: { value: "4000" } });
  fireEvent.change(screen.getByLabelText("项目名称"), { target: { value: "我的名称" } });
  fireEvent.change(screen.getByLabelText("硬条件（每行一项）"), { target: { value: "32GB" } });
  fireEvent.change(screen.getByLabelText("软偏好（每行一项）"), { target: { value: "临时偏好" } });
  fireEvent.change(screen.getByLabelText("软偏好（每行一项）"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /授权自动批次研究/ }));
  await act(async () => resolve(response));
  expect(screen.getByLabelText("预算上限（元）")).toHaveValue(4000);
  expect(screen.getByLabelText("项目名称")).toHaveValue("我的名称");
  expect(screen.getByLabelText("硬条件（每行一项）")).toHaveValue("32GB");
  expect(screen.getByLabelText("软偏好（每行一项）")).toHaveValue("");
  expect(screen.getByRole("checkbox", { name: /授权自动批次研究/ })).toBeChecked();
  expect(screen.getByText(/已填入未改动的字段/)).toBeVisible();
});

it("does not apply a late response when the source goal changed", async () => {
  const resolve = pending(); show();
  fireEvent.click(screen.getByRole("button", { name: "AI 解析需求" }));
  fireEvent.change(screen.getByLabelText("选购目标"), { target: { value: "改选相机" } });
  await act(async () => resolve(response));
  expect(screen.getByLabelText("项目名称")).toHaveValue("");
  expect(screen.getByLabelText("选购目标")).toHaveValue("改选相机");
  expect(screen.getByText("选购目标已修改，请重新解析")).toBeVisible();
});

it("blocks repeated requests and creation while parsing but keeps inputs editable", async () => {
  const resolve = pending(); show();
  const button = screen.getByRole("button", { name: "AI 解析需求" });
  fireEvent.click(button); fireEvent.click(button);
  expect(projectApi.draft).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("项目名称")).toBeEnabled();
  expect(screen.getByLabelText("选购目标")).toBeEnabled();
  expect(screen.getByRole("button", { name: "仅创建项目" })).toBeDisabled();
  await act(async () => resolve(response));
});

it("preserves inputs on failure and offers retry and manual focus without saving", async () => {
  vi.mocked(projectApi.draft).mockRejectedValueOnce(new Error("服务未返回结果")); show();
  fireEvent.change(screen.getByLabelText("项目名称"), { target: { value: "手写项目" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "AI 解析需求" })));
  expect(screen.getByRole("alert")).toHaveTextContent("需求解析未完成");
  fireEvent.click(screen.getByRole("button", { name: "手动填写" }));
  expect(screen.getByLabelText("项目名称")).toHaveFocus();
  expect(screen.getByLabelText("项目名称")).toHaveValue("手写项目");
  vi.mocked(projectApi.draft).mockResolvedValue(response);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "重试解析" })));
  expect(screen.getByText("已整理选购条件")).toBeVisible();
  expect(projectApi.draft).toHaveBeenCalledTimes(2);
  expect(projectApi.create).not.toHaveBeenCalled();
});

it("ignores a response after the drawer is unmounted", async () => {
  const resolve = pending(); const { unmount, created } = show();
  fireEvent.click(screen.getByRole("button", { name: "AI 解析需求" })); unmount();
  await act(async () => resolve(response));
  expect(created).not.toHaveBeenCalled(); expect(projectApi.create).not.toHaveBeenCalled();
});

it("reuses feedback for monitor drafts without overwriting intervening rule edits", async () => {
  let resolve!: (value: Awaited<ReturnType<typeof projectApi.monitorDraft>>) => void;
  vi.mocked(projectApi.monitorDraft).mockReturnValue(new Promise(done => { resolve = done; }));
  const saved = vi.fn(); render(<MonitorCreator id={1} goal="MacBook" close={vi.fn()} saved={saved} />);
  fireEvent.click(screen.getByRole("button", { name: "AI 生成可编辑草案" }));
  fireEvent.change(screen.getByLabelText("搜索关键词"), { target: { value: "手写关键词" } });
  await act(async () => resolve({ name: "AI 监控", keyword: "AI 关键词", mode: "once", duration_seconds: 1800, interval_seconds: 1800, max_pages: 3, max_items: 50, collect_seller_profiles: false }));
  expect(screen.getByLabelText("搜索关键词")).toHaveValue("手写关键词");
  expect(screen.getByText("已保留你的最新编辑")).toBeVisible();
  expect(saved).not.toHaveBeenCalled();
});
