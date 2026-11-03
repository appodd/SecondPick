import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";

function TestApp({ initialEntries }: { initialEntries: string[] }) {
  window.history.pushState({}, "", initialEntries[0] ?? "/");

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  );
}

function jsonResponse(payload: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

const tasksPayload = {
  items: [
    {
      id: 8,
      title: "R9000P",
      city: "上海",
      status: "active",
      run_count: 1,
      report_count: 0,
      updated_at: "2026-09-16T00:00:00+00:00",
    },
    {
      id: 9,
      title: "Pocket 3",
      city: "上海",
      status: "active",
      run_count: 1,
      report_count: 0,
      updated_at: "2026-09-17T00:00:00+00:00",
    },
  ],
  total_count: 2,
  returned_count: 2,
  truncated: false,
  page: {
    offset: 0,
    limit: 50,
    has_more: false,
    next_offset: null,
  },
};

function taskPayload(taskId: number, title: string) {
  return {
    task: {
      id: taskId,
      title,
      goal: `Find ${title}`,
      original_goal: `Find ${title}`,
      effective_goal: `Find ${title} with current preferences`,
      city: "上海",
      status: "active",
      notes: null,
      created_at: "2026-09-16T00:00:00+00:00",
      updated_at: "2026-09-16T00:00:00+00:00",
    },
    preference_revisions: [
      {
        id: taskId * 10,
        task_id: taskId,
        user_message: "Prefer complete local pickup listings.",
        effective_goal: `Find ${title} with current preferences`,
        added_preferences: ["local pickup"],
        removed_preferences: [],
        created_at: "2026-09-16T01:00:00+00:00",
      },
    ],
    runs: [],
    reports: [],
    search_coverage: {
      status: "collecting",
      unique_candidates: 1,
      target_min: 20,
      target_max: 80,
      marginal_gain_threshold: 0.1,
      low_gain_streak: 0,
      suggested_action: "continue",
      runs: [],
    },
  };
}

function candidatePagePayload(taskId: number) {
  return {
    scope: { task_id: taskId, run_ids: [taskId * 100] },
    scope_revision: "test",
    field_semantics: {
      search_description: "search result description",
      search_description_status: {
        missing: "missing",
        redundant_with_title: "same as title",
        distinct: "distinct",
      },
    },
    deduplicated_count: 1,
    returned_count: 1,
    page: {
      offset: 0,
      limit: 4,
      has_more: false,
      next_cursor: null,
    },
    candidates: [
      {
        listing_id: taskId * 1000 + 1,
        source_run_ids: [taskId * 100],
        url: `https://example.test/${taskId}`,
        title: `Candidate ${taskId}`,
        search_description: "Clean listing",
        search_description_status: "distinct",
        price_text: "5200",
        price_value: 5200,
        location: "上海",
        seller_name: "Seller A",
        search_condition: "used",
        has_detail: false,
        detail_status: "not_captured",
      },
    ],
  };
}

function debugPayload(taskId: number, title: string) {
  const task = taskPayload(taskId, title);
  return {
    task: {
      ...task.task,
      title: "DEBUG TASK TITLE",
      status: "debug-private-status",
    },
    runs: [
      {
        run_id: taskId * 10,
        role: "DEBUG RUN ROLE",
        notes: null,
        goal: "debug goal",
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
        id: taskId * 100,
        run_id: taskId * 10,
        listing_id: null,
        title: "DEBUG REPORT TITLE",
        goal: null,
        format: "DEBUG FORMAT",
        created_at: "2026-09-16T01:00:00+00:00",
      },
    ],
    search_coverage: {
      ...task.search_coverage,
      runs: [
        {
          run_id: taskId * 10,
          source_queries: ["R9000P 4060"],
          unique_in_run: 1,
          new_unique_count: 1,
          cumulative_unique_count: 1,
          new_unique_ratio: 1,
        },
      ],
    },
    global_platform_access_events: {
      scope: "global",
      warning: "These events are global and not task-scoped.",
      events: [],
    },
  };
}

let candidateRequestFails = false;
let useSensitiveTaskHeaderFixture = false;
let listing8001HasEvidence = false;
let preferredView: "research" | "debug" | null = null;
let includeReport = false;

function setViewport(width: number) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches:
        query === "(min-width: 1180px)"
          ? width >= 1180
          : query === "(max-width: 767px)"
            ? width < 768
            : false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

describe("TaskWorkspace", () => {
  beforeEach(() => {
    candidateRequestFails = false;
    useSensitiveTaskHeaderFixture = false;
    listing8001HasEvidence = false;
    preferredView = null;
    includeReport = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(input.toString(), window.location.origin);
        if (url.pathname.endsWith("/messages") || url.pathname.endsWith("/action-requests")) {
          return jsonResponse({ items: [], has_more: false, next_before_id: null });
        }

        if (url.pathname === "/api/tasks") {
          return jsonResponse(tasksPayload);
        }
        if (url.pathname === "/api/settings" && preferredView) {
          return jsonResponse({
            setup_completed: true,
            default_city: "上海",
            platforms: ["xianyu"],
            allow_ocr: true,
            preferred_view: preferredView,
          });
        }
        if (url.pathname === "/api/tasks/8") {
          const payload = taskPayload(8, "R9000P");
          return jsonResponse(
            useSensitiveTaskHeaderFixture
              ? {
                  ...payload,
                  task: {
                    ...payload.task,
                    title: "ORDINARY TASK API TITLE",
                    city: "ORDINARY TASK API CITY",
                    status: "ordinary-task-api-status",
                  },
                  reports: Array.from({ length: 7 }, (_, index) => ({
                    id: 700 + index,
                  })),
                }
              : includeReport
                ? {
                    ...payload,
                    reports: [
                      {
                        id: 91,
                        run_id: null,
                        listing_id: null,
                        title: "Saved report",
                        goal: null,
                        format: "markdown",
                        created_at: "2026-09-16T02:00:00+00:00",
                      },
                    ],
                  }
                : payload,
          );
        }
        if (url.pathname === "/api/tasks/9") {
          return jsonResponse(taskPayload(9, "Pocket 3"));
        }
        if (url.pathname === "/api/tasks/8/debug") {
          return jsonResponse(debugPayload(8, "R9000P"));
        }
        if (url.pathname === "/api/tasks/9/debug") {
          return jsonResponse(debugPayload(9, "Pocket 3"));
        }
        if (url.pathname === "/api/tasks/8/candidates") {
          if (candidateRequestFails) {
            return jsonResponse(
              {
                error: {
                  code: "service_unavailable",
                  message: "Candidate list unavailable.",
                },
              },
              { status: 503 },
            );
          }
          return jsonResponse(candidatePagePayload(8));
        }
        if (url.pathname === "/api/tasks/9/candidates") {
          return jsonResponse(candidatePagePayload(9));
        }
        if (
          url.pathname === "/api/listings/8001/evidence" &&
          url.searchParams.get("task_id") === "8"
        ) {
          if (listing8001HasEvidence) {
            return jsonResponse({
              ...candidatePagePayload(8).candidates[0],
              detail_status: "captured",
              detail: {
                snapshot_id: 1,
                run_id: 80,
                description: "mobile evidence",
                attributes: { Condition: "Verified" },
                attributes_source: "detail",
                evidence_source: "detail",
                independently_verified: false,
              },
              seller_fields: {
                seller_credit_level: null,
                seller_registered_days: null,
                seller_sold_count: null,
                seller_good_rate: null,
                seller_realname_verified: null,
                seller_reply_rate_24h: null,
                data_source: "none",
                field_sources: {},
                source: "platform_seller_field",
                independently_verified: false,
              },
              seller_other_items: [],
              evidence_conflicts: [],
              collection_state: {
                detail_snapshot_count: 1,
                valid_detail_snapshot_count: 1,
                blocked_detail_snapshot_count: 0,
                listing_lifetime_product_image_count: 0,
                listing_lifetime_downloaded_product_image_count: 0,
                listing_lifetime_ocr_result_count: 0,
              },
              raw_text_excerpt: null,
            });
          }
          return jsonResponse(
            {
              error: {
                code: "invalid_request",
                message: "Listing is outside the candidate scope.",
              },
            },
            { status: 400 },
          );
        }
        if (
          url.pathname === "/api/listings/8002/evidence" &&
          url.searchParams.get("task_id") === "8"
        ) {
          return jsonResponse({
            ...candidatePagePayload(8).candidates[0],
            listing_id: 8002,
            title: "PRIVATE LISTING TITLE",
            detail_status: "captured",
            detail: {
              snapshot_id: 1,
              run_id: 80,
              description: "private description",
              attributes: { "PRIVATE ATTRIBUTE": "PRIVATE ATTRIBUTE VALUE" },
              attributes_source: "detail",
              evidence_source: "detail",
              independently_verified: false,
            },
            seller_fields: {
              seller_credit_level: null,
              seller_registered_days: null,
              seller_sold_count: null,
              seller_good_rate: null,
              seller_realname_verified: null,
              seller_reply_rate_24h: null,
              data_source: "none",
              field_sources: {},
              source: "platform_seller_field",
              independently_verified: false,
            },
            seller_other_items: [],
            evidence_conflicts: [],
            collection_state: {
              detail_snapshot_count: 1,
              valid_detail_snapshot_count: 1,
              blocked_detail_snapshot_count: 0,
              listing_lifetime_product_image_count: 0,
              listing_lifetime_downloaded_product_image_count: 0,
              listing_lifetime_ocr_result_count: 0,
            },
            raw_text_excerpt: null,
          });
        }

        return jsonResponse({ error: { code: "not_found", message: "Not Found" } });
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("switches tasks without losing the selected research tab", async () => {
    render(
      <TestApp
        initialEntries={[
          "/tasks/8?tab=candidates&view=debug&listing=8002&context=open",
        ]}
      />,
    );

    await userEvent.click(await screen.findByRole("link", { name: /Pocket 3/ }));

    expect(screen.getByRole("heading", { name: "调试视图" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/tasks/9");
    expect(window.location.search).toContain("tab=candidates");
    expect(window.location.search).toContain("view=debug");
    expect(window.location.search).not.toContain("listing=");
    expect(window.location.search).not.toContain("context=");
  });

  it("opens and closes the mobile evidence drawer through URL state", async () => {
    listing8001HasEvidence = true;
    setViewport(390);
    render(<TestApp initialEntries={["/tasks/8?tab=candidates"]} />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Candidate 8" }),
    );

    expect(window.location.search).toContain("listing=8001");
    expect(window.location.search).toContain("context=open");
    expect(await screen.findByRole("dialog", { name: "上下文检查器" }))
      .toHaveTextContent("Verified");
    expect(document.body).toHaveStyle({ overflow: "hidden" });

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "上下文检查器" }))
      .not.toBeInTheDocument();
    expect(window.location.search).not.toContain("context=open");
    expect(document.body).not.toHaveStyle({ overflow: "hidden" });

    await userEvent.click(screen.getByRole("button", { name: "查看证据" }));
    expect(window.location.search).toContain("context=open");
    await userEvent.click(screen.getByRole("button", { name: "关闭上下文检查器" }));
    expect(window.location.search).not.toContain("context=open");

    await userEvent.click(screen.getByRole("button", { name: "查看证据" }));
    expect(window.location.search).toContain("context=open");
    await userEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(window.location.search).not.toContain("context=open");
  });

  it("opens the tablet evidence drawer from an existing context URL", async () => {
    setViewport(900);
    render(
      <TestApp
        initialEntries={[
          "/tasks/8?tab=candidates&listing=8002&context=open",
        ]}
      />,
    );

    const dialog = await screen.findByRole("dialog", { name: "上下文检查器" });
    expect(await within(dialog).findByText("PRIVATE ATTRIBUTE VALUE"))
      .toBeInTheDocument();
  });

  it("closes the mobile task drawer after route navigation", async () => {
    setViewport(390);
    render(<TestApp initialEntries={["/tasks/8"]} />);

    const trigger = await screen.findByRole("button", { name: "查看任务" });
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole("link", { name: /Pocket 3/ }));

    expect(window.location.pathname).toBe("/tasks/9");
    expect(screen.queryByRole("dialog", { name: "研究任务" }))
      .not.toBeInTheDocument();
    expect(trigger).not.toHaveFocus();
    expect(document.body).not.toHaveStyle({ overflow: "hidden" });
  });

  it("cleans unsupported task query parameters", async () => {
    render(
      <TestApp
        initialEntries={[
          "/tasks/8?tab=unknown&listing=1.5&view=other&context=side&extra=1",
        ]}
      />,
    );

    await screen.findByRole("heading", { name: "R9000P" });

    expect(window.location.search).toBe("");
  });

  it("keeps the task workspace available when optional setup data is malformed", async () => {
    render(<TestApp initialEntries={["/tasks/8"]} />);

    expect(
      await screen.findByRole("heading", { name: "R9000P" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("对话时间线")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("clears selected listing when the evidence request fails", async () => {
    render(
      <TestApp initialEntries={["/tasks/8?tab=candidates&listing=8001"]} />,
    );

    expect(
      await screen.findByText("Listing is outside the candidate scope."),
    ).toBeInTheDocument();
    expect(window.location.search).not.toContain("listing=8001");
  });

  it("keeps an API-authorized listing outside the first candidate page", async () => {
    render(
      <TestApp initialEntries={["/tasks/8?tab=candidates&listing=8002"]} />,
    );

    await screen.findByText("Candidate 8");

    expect(window.location.search).toContain("listing=8002");
  });

  it("isolates debug content while preserving the selected listing", async () => {
    useSensitiveTaskHeaderFixture = true;
    render(
      <TestApp
        initialEntries={[
          "/tasks/8?tab=candidates&listing=8002&context=open",
        ]}
      />,
    );

    expect(await screen.findByText("PRIVATE ATTRIBUTE VALUE"))
      .toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "调试视图" }));

    expect(await screen.findByRole("heading", { name: "调试视图" }))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "调试范围" }))
      .toBeInTheDocument();
    expect(window.location.search).toContain("view=debug");
    expect(window.location.search).toContain("listing=8002");
    expect(window.location.search).not.toContain("context=");
    expect(screen.queryByText("PRIVATE ATTRIBUTE VALUE"))
      .not.toBeInTheDocument();
    expect(screen.queryByText("DEBUG TASK TITLE")).not.toBeInTheDocument();
    expect(screen.queryByText("DEBUG RUN ROLE")).not.toBeInTheDocument();
    expect(screen.queryByText("DEBUG REPORT TITLE")).not.toBeInTheDocument();
    expect(screen.queryByText("DEBUG FORMAT")).not.toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(within(main).queryByText("ORDINARY TASK API TITLE"))
      .not.toBeInTheDocument();
    expect(
      within(main).queryByText(
        "ORDINARY TASK API CITY · ordinary-task-api-status",
      ),
    ).not.toBeInTheDocument();
    expect(within(main).queryByText("7", { selector: "dd" }))
      .not.toBeInTheDocument();
    expect(main.querySelector(".task-header")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "研究视图" }));

    expect(window.location.search).toContain("listing=8002");
    expect(await screen.findByText("PRIVATE ATTRIBUTE VALUE"))
      .toBeInTheDocument();
  });

  it("shows an evidence error in the active conversation panel", async () => {
    render(<TestApp initialEntries={["/tasks/8?listing=8001"]} />);

    expect(
      await screen.findByText("Listing is outside the candidate scope."),
    ).toBeInTheDocument();
    expect(window.location.search).not.toContain("listing=8001");
  });

  it("preserves legacy task context and enables continued conversation", async () => {
    render(<TestApp initialEntries={["/tasks/8"]} />);

    const timeline = await screen.findByLabelText("对话时间线");
    const composer = screen.getByRole("textbox", { name: "对话输入" });
    const timelineText = timeline.textContent ?? "";

    expect(timelineText.indexOf("Find R9000P")).toBeLessThan(
      timelineText.indexOf("Prefer complete local pickup listings."),
    );
    expect(screen.getByText("当前任务状态")).toBeInTheDocument();
    expect(screen.getByLabelText("当前候选摘录")).toBeInTheDocument();
    expect(screen.queryByText(/推荐/)).not.toBeInTheDocument();
    expect(await screen.findByText("继续聊聊这个研究任务，消息将自动保存。")).toBeInTheDocument();
    expect(composer).toBeEnabled();
    expect(composer).toHaveValue("");
  });

  it("links saved reports through the task-scoped report endpoint", async () => {
    includeReport = true;
    render(<TestApp initialEntries={["/tasks/8"]} />);

    expect(await screen.findByRole("link", { name: "Saved report" }))
      .toHaveAttribute("href", "/api/tasks/8/reports/91");
  });

  it("uses the persisted preferred view when the URL has no view", async () => {
    preferredView = "debug";
    render(<TestApp initialEntries={["/tasks/8"]} />);

    expect(await screen.findByRole("heading", { name: "调试视图" }))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "调试视图" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(window.location.search).not.toContain("view=");
  });

  it("shows a scoped error when candidate loading fails", async () => {
    candidateRequestFails = true;

    render(<TestApp initialEntries={["/tasks/8"]} />);

    expect(await screen.findByText("Candidate list unavailable.")).toHaveAttribute(
      "role",
      "status",
    );
  });
});
