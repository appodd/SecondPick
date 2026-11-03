import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ProjectOverview, Study } from "../../api/projectClient";
import { GoalContinuityNotice, GoalContinuityProvider, calibrationLabel } from "./GoalContinuity";
import { studyStatus } from "../../components/status/statusModel";

const context: NonNullable<ProjectOverview["goal_context"]> = { current_revision: 2, original_goal: "买电脑", report_current: false, calibration: "pending", legacy_unmerged: false, updated_at: "2026-10-23", automatic_calibration_supported: true };
describe("goal calibration server states", () => {
  it("distinguishes waiting, scheduled, running, ready and unavailable without guessed progress", () => {
    expect(calibrationLabel(context)).toContain("研究结论待校准");
    expect(calibrationLabel({ ...context, calibration_work: { state: "scheduled", reason: "已入队", listing_ids: [1], study_id: 23 } })).toContain("校准研究已安排");
    expect(calibrationLabel({ ...context, calibration: "running" })).toContain("正在按目标 v2 研究");
    expect(calibrationLabel({ ...context, calibration: "current", report_current: true })).toContain("研究结论已就绪");
    expect(calibrationLabel({ ...context, calibration_work: { state: "unavailable", reason: "已暂停", listing_ids: [], study_id: null } })).toContain("无法自动研究");
    expect(calibrationLabel({ ...context, calibration_work: { state: "not_needed", reason: "仅软偏好", listing_ids: [], study_id: null } })).toContain("暂不自动重研");
  });
  it("shows real queue reason and link, and does not label scheduled as running", () => {
    const data = { project: { id: 1 }, studies: [], goal_context: { ...context, calibration_work: { state: "scheduled", reason: "已受理，等待本项目现有研究结束", listing_ids: [1,2], study_id: 23 } } } as unknown as ProjectOverview;
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><GoalContinuityProvider data={data}><GoalContinuityNotice data={data} /></GoalContinuityProvider></MemoryRouter></QueryClientProvider>);
    expect(screen.getByText("目标 v2 校准研究已安排")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看校准研究 →" })).toHaveAttribute("href", "/projects/1?view=research#research-run-23");
    expect(screen.queryByText(/正在按目标/)).toBeNull();
    expect(screen.getByRole("complementary").textContent).not.toContain("%");
  });
  it("obsolete unstarted calibration is neither failure nor successful analysis", () => {
    expect(studyStatus({ state: "superseded" } as Study)).toMatchObject({ kind: "inactive", label: "目标已变更 · 本次未执行" });
  });
});
