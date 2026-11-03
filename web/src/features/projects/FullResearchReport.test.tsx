import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { FullResearchReport } from "./FullResearchReport";
import type { Report } from "../../api/projectClient";
afterEach(cleanup);

it("a late old-goal report with a higher id never turns the current-goal report into a newer historical claim", () => {
  const saved = { id: 42, goal_revision: 1, content: "旧目标晚完成的历史结果", candidate_ids_json: "[]", snapshot_at: "2026-10-22T00:00:00Z", created_at: "2026-10-23T00:00:00Z", limited: 1 } satisfies Report;
  render(<FullResearchReport report={saved} latest={{ ...saved, id: 40, goal_revision: 2 }} close={() => {}} readLatest={() => {}} />);
  expect(screen.getByText(/本报告基于目标 v1/)).toBeVisible();
  expect(screen.getByRole("button", { name: "查看当前目标报告" })).toBeVisible();
  expect(screen.queryByText(/已有新报告/)).not.toBeInTheDocument();
});
