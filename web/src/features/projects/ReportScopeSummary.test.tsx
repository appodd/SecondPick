import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { ProjectOverview } from "../../api/projectClient";
import { GoalContinuityProvider } from "./GoalContinuity";
import { ReportScopeSummary } from "./ReportScopeSummary";
afterEach(cleanup);

const data = { project: { id: 1 }, report: { id: 2 }, pending: 19,
  goal_context: { current_revision: 2, report_current: true, legacy_unmerged: false },
  coverage: { evaluated: 3, summarized: 7, waiting: 11, needs_information: 2, rule_excluded: 6 } } as unknown as ProjectOverview;
function show(value=data, unavailable=false) {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><GoalContinuityProvider data={value} unavailable={unavailable}><ReportScopeSummary data={value} /></GoalContinuityProvider></MemoryRouter></QueryClientProvider>);
}
describe("finite report coverage", () => {
  it("keeps limited scope and continuation visible while folding counting details", () => {
    show();
    expect(screen.getByText("本报告仅覆盖有限样本，不代表全部商品都已研究。")).toBeVisible();
    const counts=screen.getByText(/已逐项分析 3 件，另有 7 件仅有批次概述/);
    expect(counts).not.toBeVisible();
    expect(screen.getByRole("link",{name:"继续研究剩余商品 →"})).toBeVisible();
    fireEvent.click(screen.getByText("查看研究范围"));
    expect(counts.closest("details")).toHaveAttribute("open");
  });
  it("makes remaining work reachable and never counts rule exclusions or summaries as analysis", () => {
    show();
    expect(screen.getByLabelText("当前报告研究范围")).toHaveTextContent("已逐项分析 3 件，另有 7 件仅有批次概述；13 件等待安排或补充信息");
    expect(screen.getByRole("link", { name: "继续研究剩余商品 →" })).toHaveAttribute("href", expect.stringContaining("view=research"));
    expect(screen.getByLabelText("当前报告研究范围")).not.toHaveTextContent("19 件等待");
  });
  it("never labels a historical or unavailable goal as current coverage", () => {
    show(data,true);
    expect(screen.queryByLabelText("当前报告研究范围")).toBeNull();
  });
});
