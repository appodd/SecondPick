import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./client";

function validDebugPayload() {
  return {
    task: { id: 8 },
    runs: [
      {
        run_id: 81,
        query_count: 3,
        page_snapshot_count: 4,
        listing_snapshot_count: 2,
      },
    ],
    reports: [{ id: 91 }],
    search_coverage: {
      status: "collecting",
      unique_candidates: 12,
      target_min: 20,
      target_max: 80,
      low_gain_streak: 0,
      suggested_action: "continue",
      runs: [{ run_id: 81, new_unique_count: 12 }],
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
  };
}

function stubDebugResponse(payload: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(payload), {
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("API error handling", () => {
  it.each([
    ["", "text/plain"],
    ["<html>upstream failure</html>", "text/html"],
  ])("wraps non-JSON HTTP failures as ApiError", async (body, contentType) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(body, {
          status: 502,
          headers: { "Content-Type": contentType },
        }),
      ),
    );

    const failure = await api.getTasks().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      status: 502,
      code: "http_error",
      message: "Request failed.",
    });
  });
});

describe("api.checkCodex", () => {
  it("posts to the setup-scoped Codex check endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          cli_available: true,
          auth_available: true,
          process_running: false,
          detail: "authenticated",
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.checkCodex();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/setup/" + "check-codex",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("api.getDebug", () => {
  it("rejects a null run before it reaches the debug workspace", async () => {
    const payload = validDebugPayload();
    payload.runs = [null] as never[];
    stubDebugResponse(payload);

    await expect(api.getDebug(8)).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("rejects malformed nested coverage, report, and access event fields", async () => {
    const payload = validDebugPayload();
    payload.reports = [{ id: "91" }] as never[];
    payload.search_coverage.runs = [
      { run_id: 81, new_unique_count: "12" },
    ] as never[];
    payload.global_platform_access_events.events = [null] as never[];
    stubDebugResponse(payload);

    await expect(api.getDebug(8)).rejects.toMatchObject({
      code: "invalid_response",
    });
  });
});
