import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DebugSnapshot } from "../../api/types";
import { DebugWorkspace } from "./DebugWorkspace";

const snapshot = {
  task: {
    id: 8,
    title: "R9000P",
    goal: "Find R9000P",
    original_goal: "Find R9000P",
    effective_goal: "Find R9000P in 上海",
    city: "上海",
    status: "ready",
    notes: null,
    created_at: "2026-09-16T00:00:00+00:00",
    updated_at: "2026-09-16T01:00:00+00:00",
  },
  runs: [
    {
      run_id: 81,
      role: "PRIVATE RUN ROLE",
      notes: null,
      goal: "Find R9000P",
      city: "上海",
      query_count: 3,
      page_snapshot_count: 4,
      listing_snapshot_count: 2,
      run_created_at: "2026-09-16T00:30:00+00:00",
      attached_at: "2026-09-16T00:40:00+00:00",
      source_queries: ["R9000P 4060"],
    },
  ],
  reports: [
    {
      id: 91,
      run_id: 81,
      listing_id: null,
      title: "Research report",
      goal: null,
      format: "markdown",
      created_at: "2026-09-16T01:00:00+00:00",
    },
  ],
  search_coverage: {
    status: "collecting",
    unique_candidates: 12,
    target_min: 20,
    target_max: 80,
    marginal_gain_threshold: 0.1,
    low_gain_streak: 0,
    suggested_action: "continue",
    runs: [
      {
        run_id: 81,
        source_queries: ["R9000P 4060"],
        unique_in_run: 12,
        new_unique_count: 12,
        cumulative_unique_count: 12,
        new_unique_ratio: 1,
      },
    ],
  },
  global_platform_access_events: {
    scope: "global",
    warning: "These events are global and not task-scoped.",
    events: [
      {
        id: 17,
        platform: "xianyu",
        operation: "search",
        target: "R9000P 4060",
        attempted_at: "2026-09-16T00:20:00+00:00",
      },
    ],
  },
  raw_html: "<html>secret</html>",
  cookie_content: "session=secret",
  full_ocr_text: "private full OCR",
} as DebugSnapshot;

afterEach(cleanup);

describe("DebugWorkspace", () => {
  it("renders task coverage, run counts, report IDs, and global events", () => {
    render(<DebugWorkspace snapshot={snapshot} />);

    expect(screen.getByRole("heading", { name: "调试视图" })).toBeInTheDocument();
    expect(screen.getByText("12 / 20–80")).toBeInTheDocument();
    expect(screen.getByText("查询 3")).toBeInTheDocument();
    expect(screen.getByText("页面快照 4")).toBeInTheDocument();
    expect(screen.getByText("详情快照 2")).toBeInTheDocument();
    expect(screen.getByText("报告 #91")).toBeInTheDocument();
    expect(screen.getByText("These events are global and not task-scoped."))
      .toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "R9000P 4060" }))
      .toBeInTheDocument();
  });

  it("never renders sensitive raw payloads or report metadata", () => {
    render(<DebugWorkspace snapshot={snapshot} />);

    expect(screen.queryByText("<html>secret</html>"))
      .not.toBeInTheDocument();
    expect(screen.queryByText("session=secret")).not.toBeInTheDocument();
    expect(screen.queryByText("private full OCR")).not.toBeInTheDocument();
    expect(screen.queryByText("R9000P")).not.toBeInTheDocument();
    expect(screen.queryByText("ready")).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE RUN ROLE")).not.toBeInTheDocument();
    expect(screen.queryByText("Research report")).not.toBeInTheDocument();
    expect(screen.queryByText("markdown")).not.toBeInTheDocument();
  });
});
