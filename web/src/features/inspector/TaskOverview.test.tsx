import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { TaskDetail } from "../../api/types";
import { TaskOverview } from "./TaskOverview";

const taskDetail: TaskDetail = {
  task: {
    id: 8,
    title: "R9000P",
    goal: "找一台 R9000P",
    original_goal: "找一台 R9000P",
    effective_goal: "找可靠、支持本地自提的 R9000P",
    city: "上海",
    status: "active",
    notes: null,
    created_at: "2026-09-16T00:00:00+00:00",
    updated_at: "2026-09-16T02:00:00+00:00",
  },
  preference_revisions: [
    {
      id: 1,
      task_id: 8,
      user_message: "先看低价和本地自提",
      effective_goal: "找低价、支持本地自提的 R9000P",
      added_preferences: ["低价优先", "本地自提"],
      removed_preferences: [],
      created_at: "2026-09-16T01:00:00+00:00",
    },
    {
      id: 2,
      task_id: 8,
      user_message: "不再低价优先，改为可靠性优先",
      effective_goal: "找可靠、支持本地自提的 R9000P",
      added_preferences: ["可靠性优先"],
      removed_preferences: ["低价优先"],
      created_at: "2026-09-16T02:00:00+00:00",
    },
  ],
  runs: [],
  reports: [],
  search_coverage: {
    status: "collecting",
    unique_candidates: 0,
    target_min: 20,
    target_max: 80,
    marginal_gain_threshold: 0.1,
    low_gain_streak: 0,
    suggested_action: "continue",
    runs: [],
  },
};

describe("TaskOverview", () => {
  afterEach(cleanup);
  it("uses full-state preferences and run totals instead of the bounded page", () => {
    render(<TaskOverview taskDetail={{ ...taskDetail, preference_revisions: [], current_preferences: ["早期保留偏好"],
      history_page: { limit: 10, has_more: true, next_cursor: "older", total_counts: { runs: 23, reports: 0, preference_revisions: 23 } } }} />);
    expect(screen.getByText("早期保留偏好")).toBeInTheDocument();
    expect(screen.getByText("23")).toBeInTheDocument();
  });

  it("renders only preferences that remain effective after all revisions", () => {
    render(<TaskOverview taskDetail={taskDetail} />);

    expect(screen.getByText("本地自提")).toBeInTheDocument();
    expect(screen.getByText("可靠性优先")).toBeInTheDocument();
    expect(screen.queryByText("低价优先")).not.toBeInTheDocument();
  });
});
