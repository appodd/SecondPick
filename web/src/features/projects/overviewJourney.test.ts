import { describe, expect, it } from "vitest";
import type { ProjectOverview } from "../../api/projectClient";
import { overviewJourney } from "./overviewJourney";

export function sample(): ProjectOverview {
  return { project: { id: 1, title: "选购项目", goal: "预算内选购", status: "active" }, policy: { budget: 500, hard: [], soft: [], minimum: 20, paused: 0, auto_research: 0 }, total: 0, eligible: 0, pending: 0, coverage: { evaluated: 0, summarized: 0, waiting: 0, needs_information: 0 }, phase: "collecting_baseline", report: null, cards: [], favorites: [], changes: [], studies: [], goal_context: { current_revision: 1, original_goal: "预算内选购", report_current: true, calibration: "current", legacy_unmerged: false, updated_at: "2026-10-27", automatic_calibration_supported: true } };
}
describe("overview next step is navigation, never scheduling", () => {
  it("connects a new project to its existing monitor plan", () => expect(overviewJourney(sample())).toMatchObject({ kind: "empty", view: "monitors", step: 0 }));
  it("distinguishes collected products from comparable samples", () => { const d = sample(); d.total = 30; d.eligible = 4; expect(overviewJourney(d)).toMatchObject({ kind: "collecting", view: "monitors" }); expect(overviewJourney(d).description).toContain("4 / 20"); });
  it("does not promise automatic research when disabled", () => { const d = sample(); d.total = d.eligible = 20; expect(overviewJourney(d).description).toContain("自动研究未开启"); expect(overviewJourney(d).view).toBe("research"); });
  it("distinguishes queued from running", () => { const d = sample(); d.studies = [{ state: "queued" }] as ProjectOverview["studies"]; expect(overviewJourney(d).kind).toBe("queued"); d.studies[0].state = "running"; expect(overviewJourney(d).kind).toBe("running"); });
  it("does not hide an existing running task after pausing", () => { const d = sample(); d.policy.paused = 1; d.studies = [{ state: "running" }] as ProjectOverview["studies"]; expect(overviewJourney(d).description).toContain("已有任务仍在执行"); });
  it("keeps monitoring independent of research pause", () => { const d = sample(); d.policy.paused = 1; expect(overviewJourney(d)).toMatchObject({ kind: "paused", view: "research" }); expect(overviewJourney(d).description).toContain("监控采集是否运行请查看"); });
  it("preserves saved results after completion", () => { const d = sample(); d.project.status = "completed"; expect(overviewJourney(d).kind).toBe("completed"); });
  it("routes failed work to history without a retry action", () => { const d = sample(); d.studies = [{ state: "failed" }] as ProjectOverview["studies"]; expect(overviewJourney(d)).toMatchObject({ kind: "attention", view: "research" }); expect(overviewJourney(d).description).toContain("不会自动重试"); });
  it.each(["evidence", "goal"])("does not call a stale %s report current", kind => { const d = sample(); d.report = { evidence_current: kind !== "evidence" } as ProjectOverview["report"]; if (kind === "goal") d.goal_context!.report_current = false; expect(overviewJourney(d)).toMatchObject({ kind: "attention", view: "research" }); });
  it("routes usable reports to candidate comparison", () => { const d = sample(); d.report = {} as ProjectOverview["report"]; expect(overviewJourney(d)).toMatchObject({ kind: "ready", view: "shortlist" }); });
});
