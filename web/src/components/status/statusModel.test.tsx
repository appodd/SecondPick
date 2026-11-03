import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { Monitor, MonitorPage } from "../../api/monitorClient";
import type { ProjectOverview, Study, WindowMonitor } from "../../api/projectClient";
import { monitorExecution, monitorScheduling, productResearchStatus, projectMonitorExecution, researchExecution, researchScheduling, studyStatus, windowStatus } from "./statusModel";
import { ExecutionStatus, ProgressSummary, snapshotStatus, StatusBadge, StatusSnapshot } from "./ExecutionStatus";
import { AgentResearchStatus } from "../../features/projects/AgentResearchStatus";

afterEach(cleanup);
const monitor = { state: "waiting", desired_state: null, error_code: null, next_run_at: null, updated_at: "2026-10-22T02:00:00Z", result: {} } as Monitor;
const study = { id: 1, kind: "initial", state: "queued", created_at: "2026-10-22T02:00:00Z", finished_at: null, error: null, listing_ids: [1], result: null } as Study;
const project = { project: { id: 1, status: "active" }, policy: { paused: 0, auto_research: 1, minimum: 20 },
  studies: [], phase: "incremental", total: 9, eligible: 3, report: { id: 1 }, coverage: { waiting: 2, under_ai: 0, evaluated: 7 } } as unknown as ProjectOverview;
const work: NonNullable<ProjectOverview["research_work"]> = { goal_revision: 1, total: 99, unassessed: 87, batch_limit: 10,
  counts: { evaluated: 12, ready: 4, needs_evidence: 83, no_priority: 0, attempted: 0, failed: 0, queued: 0, running: 0, rule_excluded: 0 },
  gate: "ready", reason: "已有明确补研线索，不自动研究全部商品", listing_ids: [1879,1881,1887,1889], items: [], quota: "unknown" };

describe("followup selection and research coverage", () => {
  it("shows unassessed separately from ready work without inferring a percentage", () => {
    render(<AgentResearchStatus data={{ ...project, total: 99, coverage: { evaluated: 12, summarized: 87, waiting: 0, under_ai: 0 }, research_work: work }} />);
    expect(screen.getByLabelText("核心研究统计")).toHaveTextContent("12已逐项分析0已安排研究87尚未逐项研究");
    expect(screen.getByLabelText("后续研究安排")).toHaveTextContent("可有限补研 4 件");
    expect(screen.getByLabelText("后续研究安排")).toHaveTextContent("需补证据或指定重点 83 件");
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
  it("does not invent provider quota or call an idle queue an absence of research value", () => {
    expect(researchExecution({ ...project, research_work: work }).reason).toBe(work.reason);
    render(<AgentResearchStatus data={{ ...project, research_work: work }} />);
    expect(screen.getByLabelText("后续研究安排")).toHaveTextContent("账号剩余额度暂不可确认");
  });
  it("distinguishes a failed bounded attempt from a paused entire scheduler", () => {
    const data = { ...project, research_work: { ...work, gate: "idle", counts: { ...work.counts, ready: 0, failed: 4 } } };
    expect(researchExecution(data).label).toBe("有限补研需要处理");
    expect(researchScheduling(data).label).toBe("自动研究已启用");
  });
  it("honors a real current-goal failure gate and pause before claiming eligibility", () => {
    expect(researchScheduling({ ...project, research_work: { ...work, gate: "failed" } }).kind).toBe("attention");
    expect(researchScheduling({ ...project, policy: { ...project.policy, paused: 1 }, research_work: work }).kind).toBe("paused");
  });
});

describe("shared execution truth boundaries", () => {
  it("aggregates native monitoring without treating enabled configuration as active execution", () => {
    const page = { enabled: true, platform_enabled: true, candidate_pool_count: 3, items: [monitor] } as MonitorPage;
    expect(projectMonitorExecution(page).kind).toBe("waiting");
    expect(projectMonitorExecution({ ...page, items: [] }).label).toBe("尚无监控");
    expect(projectMonitorExecution({ ...page, items: [{ ...monitor, state: "paused" }] }).kind).toBe("paused");
    expect(projectMonitorExecution({ ...page, items: [{ ...monitor, state: "paused" }, { ...monitor, state: "running" }] }).kind).toBe("running");
    expect(projectMonitorExecution({ ...page, enabled: false }).kind).toBe("inactive");
    expect(projectMonitorExecution({ ...page, items: [{ ...monitor, state: "future" as Monitor["state"] }] }).kind).toBe("unknown");
  });
  it("does not present an enabled monitor or a running window as active collection", () => {
    expect(monitorScheduling(monitor).kind).toBe("ready");
    expect(monitorExecution(monitor).kind).toBe("waiting");
    expect(windowStatus({ state: "running" } as WindowMonitor["runs"][number], monitor).kind).toBe("waiting");
  });
  it("shows actual running collection, including pending stop cleanup, in blue", () => {
    const value = monitorExecution({ ...monitor, state: "running", desired_state: "stopped" });
    expect(value.kind).toBe("running");
    expect(value.action).toContain("停止监控并保存");
  });
  it("keeps restarts and failures distinct from a clean pause or expected cancellation", () => {
    expect(monitorExecution({ ...monitor, state: "paused" }).kind).toBe("paused");
    expect(monitorExecution({ ...monitor, state: "paused", error_code: "service_restarted" }).kind).toBe("attention");
    expect(monitorExecution({ ...monitor, state: "stopped", error_code: "cancelled" }).kind).toBe("inactive");
    expect(monitorExecution({ ...monitor, state: "needs_attention", error_code: "engine_failed" }).kind).toBe("attention");
  });
  it("does not infer success from a stopped monitor or a completed execution window", () => {
    expect(monitorExecution({ ...monitor, state: "stopped" }).kind).toBe("inactive");
    expect(windowStatus({ state: "completed" } as WindowMonitor["runs"][number]).kind).toBe("inactive");
    expect(studyStatus({ ...study, state: "completed" }).kind).toBe("success");
  });
  it("keeps automatic research enabled but idle when a report already exists", () => {
    expect(researchScheduling(project).kind).toBe("ready");
    expect(researchExecution(project).kind).toBe("waiting");
    expect(researchExecution(project).label).toContain("当前空闲");
  });
  it("does not mark queued research or under_ai product coverage as executing", () => {
    expect(researchExecution({ ...project, studies: [study], coverage: { ...project.coverage, under_ai: 2 } }).kind).toBe("waiting");
    expect(productResearchStatus("under_ai").kind).toBe("waiting");
    expect(productResearchStatus("queued").kind).toBe("waiting");
  });
  it("keeps a real AgentRun running after scheduling is paused or the project ends", () => {
    const data = { ...project, policy: { ...project.policy, paused: 1 }, studies: [{ ...study, state: "running" }] };
    expect(researchScheduling(data).kind).toBe("paused");
    expect(researchExecution(data).kind).toBe("running");
    expect(researchExecution({ ...data, project: { ...data.project, status: "completed" } }).kind).toBe("running");
  });
  it("detects automatic research blocking without treating a selected-task failure as scheduler failure", () => {
    expect(researchScheduling({ ...project, studies: [{ ...study, state: "failed" }] }).kind).toBe("attention");
    expect(researchScheduling({ ...project, studies: [{ ...study, state: "failed", kind: "selected" }] }).kind).toBe("ready");
  });
  it("marks incomplete, inconsistent and truncated task information as unknown", () => {
    expect(monitorExecution({ ...monitor, state: "future_state" } as unknown as Monitor).kind).toBe("unknown");
    expect(researchExecution({ ...project, studies: Array.from({ length: 30 }, (_, id) => ({ ...study, id, state: "completed" })) }).kind).toBe("unknown");
    expect(researchExecution({ ...project, coverage: { ...project.coverage, under_ai: 2 } }).kind).toBe("unknown");
  });
  it("revokes live-running presentation when a snapshot fails or expires", () => {
    const active = studyStatus({ ...study, state: "running" });
    expect(snapshotStatus(active, { observedAt: 1000, now: 30000, staleAfterMs: 15000, unavailable: false }).kind).toBe("unknown");
    expect(snapshotStatus(active, { observedAt: 29000, now: 30000, staleAfterMs: 15000, unavailable: true }).kind).toBe("unknown");
    render(<StatusSnapshot observedAt={Date.now()} unavailable><ExecutionStatus status={active} /></StatusSnapshot>);
    expect(screen.getByText("状态暂不可确认")).toBeVisible();
    expect(document.querySelector('[data-kind="running"]')).toBeNull();
  });
  it("only renders measurable progress when both completed and total are reliable", () => {
    const { rerender } = render(<ProgressSummary total={30} />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    rerender(<ProgressSummary completed={11} total={30} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "11");
    rerender(<ProgressSummary completed={40} total={30} />);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
  it("uses shared semantic attributes and only animates running states", () => {
    const { rerender } = render(<StatusBadge status={monitorExecution(monitor)} />);
    expect(screen.getByText("等待下一轮")).toHaveAttribute("data-kind", "waiting");
    rerender(<StatusBadge status={monitorExecution({ ...monitor, state: "running" })} />);
    expect(screen.getByText("正在采集")).toHaveAttribute("data-kind", "running");
  });
  it("renders idle research counts without claiming the pipeline is executing", () => {
    render(<AgentResearchStatus data={project} />);
    expect(screen.getByText("自动研究已启用")).toBeVisible();
    expect(screen.getByText("本项目研究当前空闲")).toBeVisible();
    expect(document.querySelector('[data-kind="running"]')).toBeNull();
    expect(screen.getByLabelText("核心研究统计").children).toHaveLength(3);
    expect(screen.getAllByText("等待安排")[0].previousSibling).toHaveTextContent("2");
  });
  it("does not count batch summaries as individual analysis or infer missing counts", () => {
    render(<AgentResearchStatus data={{ ...project, total: 116, coverage: { evaluated: 17, under_ai: 16, summarized: 82 } }} />);
    const metrics = screen.getByLabelText("核心研究统计");
    expect(metrics).toHaveTextContent("17已逐项分析16已安排研究—等待安排");
    expect(screen.getByText("另有 82 件仅有批次概述，尚无逐项评价。")).toBeVisible();
    expect(screen.getAllByText("已安排研究")[0]).toHaveAttribute("title", expect.stringContaining("不代表每件商品此刻正在分析"));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
  it("keeps truncated task totals and their limitations inside coverage details", () => {
    render(<AgentResearchStatus data={{ ...project, studies: Array.from({ length: 30 }, (_, id) => ({ ...study, id, state: "completed" })) }} />);
    expect(screen.getByText("状态未知")).toBeVisible();
    const details = document.querySelector(".sp-research-coverage");
    expect(details).not.toHaveAttribute("open");
    expect(details).toHaveTextContent("可能缺少更早的活动任务");
    expect(details).toHaveTextContent("执行状态暂不可确认");
  });
});
