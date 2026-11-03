import { describe, expect, it } from "vitest";
import type { Monitor, MonitorPage } from "../../api/monitorClient";
import type { ProjectOverview } from "../../api/projectClient";
import { monitorExecution, projectMonitorExecution } from "../../components/status/statusModel";
import { workspaceMonitorStatus, workspaceResearchStatus } from "./workspaceRuntimeModel";

const monitor = { state: "waiting", desired_state: null, error_code: null, result: {}, next_run_at: "2026-10-22T12:00:00Z" } as Monitor;
const page = (items: Monitor[]) => ({ items, enabled: true, platform_enabled: true, candidate_pool_count: 1 }) as MonitorPage;
const project = { project: { status: "active" }, policy: { paused: 0, auto_research: 1 }, total: 1, phase: "incremental", coverage: { under_ai: 0 }, report: {}, studies: [] } as unknown as ProjectOverview;
describe("workspace runtime truth boundaries", () => {
  it("distinguishes a future plan and an arrived plan without claiming resource ownership", () => {
    const future = monitorExecution(monitor, Date.parse("2026-10-22T11:00:00Z"));
    const due = monitorExecution(monitor, Date.parse("2026-10-22T13:00:00Z"));
    expect(future.action).toContain("等待计划时间"); expect(due.action).toContain("计划时间已到");
    expect(future.kind).toBe("waiting"); expect(due.kind).toBe("waiting");
    expect(due.reason).toContain("后端未提供资源占用或排队原因");
  });
  it("does not use timezone-free or invalid plan times to claim a scheduling deadline", () => {
    expect(monitorExecution({ ...monitor, next_run_at: "2026-10-22T12:00:00" }).action).toContain("暂不可确认");
    expect(monitorExecution({ ...monitor, next_run_at: "invalid" }).action).toContain("暂不可确认");
  });
  it("shows actual collection separately from waiting and configuration enablement", () => {
    expect(workspaceMonitorStatus(page([monitor])).kind).toBe("waiting");
    expect(workspaceMonitorStatus(page([{ ...monitor, state: "running" }])).label).toBe("采集中");
    expect(workspaceMonitorStatus(page([{ ...monitor, state: "stopped" }])).label).toBe("监控停止");
  });
  it("does not claim user intent from a paused field or dismiss recorded errors", () => {
    expect(workspaceMonitorStatus(page([{ ...monitor, state: "paused" }])).label).toBe("采集暂停");
    expect(workspaceMonitorStatus(page([{ ...monitor, state: "paused", error_code: "service_restarted" }])).kind).toBe("attention");
  });
  it("cannot confirm absence of an older running monitor beyond the fifty-row limit", () => {
    const many = Array.from({ length: 50 }, () => ({ ...monitor, state: "stopped" as const }));
    expect(projectMonitorExecution(page(many)).kind).toBe("unknown");
    expect(projectMonitorExecution(page([...many, { ...monitor, state: "running" }])).kind).toBe("running");
  });
  it("never converts chat operation flags or enabled research into an executing AgentRun", () => {
    expect(workspaceResearchStatus(project).label).toBe("AI 空闲");
    expect(workspaceResearchStatus({ ...project, studies: [{ id: 1, state: "queued" } as ProjectOverview["studies"][number]] }).label).toBe("AI 等待");
    expect(workspaceResearchStatus({ ...project, studies: [{ id: 1, state: "running" } as ProjectOverview["studies"][number]] }).label).toBe("AI 研究中");
    expect(workspaceResearchStatus(undefined).kind).toBe("unknown");
  });
});
