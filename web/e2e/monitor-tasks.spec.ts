import { expect, test, type Page } from "@playwright/test";

// Synthetic responses are confined to the isolated browser test server.
async function scenario(page: Page, single = false) {
  const base = { task_id: 10, desired_state: null, keyword: "MacBook Pro M", max_pages: 3, max_items: 50,
    interval_seconds: 1800, max_rounds: 100, collect_seller_profiles: false, rounds: 3, imported: 22,
    next_run_at: "2026-10-22T04:00:00Z", updated_at: "2026-10-22T03:50:00Z", error_code: null,
    result: { worker_status: { phase: "collecting", error_code: null } } };
  const states = ["running", "waiting", "paused", "stopped", "needs_attention", "paused"];
  const native = states.map((state, i) => ({ ...base, id: 91 + i, state, error_code: i === 4 ? "verification_required" : null }));
  const items = native.slice(0, 5).map((monitor, i) => ({ monitor_id: monitor.id, name: `选购监控 ${monitor.id}`,
    mode: i === 3 ? "once" : i === 1 ? "timed" : "ongoing", duration_seconds: i === 1 ? 1800 : null,
    revision: 7, monitor, runs: [2, 1].map(n => ({ id: monitor.id * 10 + n,
      state: i < 2 ? "running" : i === 2 ? "paused" : i === 4 ? "failed" : "completed",
      started_at: base.updated_at, finished_at: i >= 3 ? base.updated_at : null, deadline_at: null,
      error: i === 4 ? "verification_required" : null, counts: { records: 22, unique_listings: 20 }, config: base })) }));
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  if (single) { native.splice(1); items.splice(1); }
  let fail = false;
  await page.route("**/api/projects/10/monitors", route => route.fulfill(fail ? { status: 503, json: { detail: "unavailable" } } : { json: { items } }));
  await page.route("**/api/tasks/10/monitors", route => route.fulfill({ json: { enabled: true, platform_enabled: true, candidate_pool_count: 0, items: native } }));
  await page.route("**/monitors/*/events?*", route => route.fulfill({ json: { items: [{ id: 1, code: "round_finished", created_at: base.updated_at, phase: "process", counts: { imported: 22 } }], has_more: false, next_before_id: null } }));
  await page.route("**/api/tasks/10/monitors/*/*", async route => {
    const request = route.request();
    if (request.method() === "GET") return route.fallback();
    writes.push({ url: request.url(), body: {} });
    const parts = new URL(request.url()).pathname.split("/");
    const monitor = native.find(item => item.id === Number(parts.at(-2)))!;
    monitor.state = parts.at(-1) === "pause" ? "paused" : parts.at(-1) === "resume" ? "waiting" : "stopped";
    monitor.error_code = null;
    await route.fulfill({ json: monitor });
  });
  await page.route("**/api/projects/10/monitors/*", async route => {
    if (route.request().method() !== "PATCH") return route.fallback();
    const body = route.request().postDataJSON(); writes.push({ url: route.request().url(), body });
    const item = items.find(item => item.monitor_id === Number(route.request().url().split("/").at(-1)))!;
    item.name = body.name; item.monitor.keyword = body.keyword; item.monitor.state = "stopped"; item.revision++;
    await route.fulfill({ json: item });
  });
  await page.route("**/api/projects/10/monitors/*/runs", async route => {
    writes.push({ url: route.request().url(), body: route.request().postDataJSON() });
    native.find(item => item.id === 94)!.state = "waiting";
    await route.fulfill({ json: {} });
  });
  const latest = "a".repeat(32), older = "b".repeat(32);
  await page.route("**/monitors/*/logs?*", route => {
    const round = new URL(route.request().url()).searchParams.get("round_id") || latest;
    return route.fulfill({ json: { items: [{ at: base.updated_at, text: round === older ? "historical collection output" : "latest collection output" }],
      rounds: [{ id: latest, updated_at: base.updated_at }, { id: older, updated_at: base.updated_at }], round_id: round,
      next_before: null, has_more: false, capture_enabled: true, max_bytes: 4194304, max_rounds: 5 } });
  });
  return { writes, native, items, fail: () => { fail = true; }, older };
}

test("compact multi-task list separates schedule, execution and native-only records", async ({ page }, info) => {
  const fixture = await scenario(page);
  await page.goto("/projects/10?view=monitors");
  const rows = page.locator(".mt-task-row");
  await expect(page.getByRole("button", { name: /快捷操作$/ })).toHaveCount(0);
  await expect(rows).toHaveCount(6);
  await expect(page.getByText("2 个调度启用", { exact: true })).toBeVisible();
  await expect(page.getByText("1 个正在采集", { exact: true })).toBeVisible();
  for (const [id, kind] of [[91, "running"], [92, "waiting"], [93, "paused"], [94, "inactive"], [95, "attention"]] as const)
    await expect(rows.filter({ has: page.getByRole("button", { name: `选购监控 ${id}`, exact: true }) }).locator(".mt-row-meta .sp-status")).toHaveAttribute("data-kind", kind);
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await expect(page.getByRole("log")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "执行历史", exact: true })).toHaveCount(0);
  await expect(page.locator(".sp-agent")).toHaveCount(0);
  expect(fixture.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("compact-multiple-monitors.png"), fullPage: true });
});

test("running monitor switch confirms its scope, keeps real state on failure and leaves the sidebar read-only", async ({ page }) => {
  const fixture = await scenario(page);
  await page.goto("/projects/10?view=monitors");
  const row = page.getByRole("article", { name: "监控任务 选购监控 91", exact: true });
  const toggle = row.getByRole("switch");
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  page.once("dialog", dialog => dialog.dismiss());
  await toggle.click(); expect(fixture.writes).toEqual([]);
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await page.route("**/api/tasks/10/monitors/91/pause", route => route.fulfill({ status: 503, json: { detail: "暂停请求失败" } }));
  page.once("dialog", dialog => dialog.accept());
  await toggle.click();
  await expect(row.getByRole("alert")).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await page.unroute("**/api/tasks/10/monitors/91/pause");
  page.once("dialog", dialog => dialog.accept());
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  expect(fixture.writes.map(write => new URL(write.url).pathname)).toEqual(["/api/tasks/10/monitors/91/pause"]);
  await expect(page.getByRole("article", { name: "监控任务 选购监控 94", exact: true }).getByRole("switch")).toHaveCount(0);
  await expect(page.getByRole("article", { name: "监控任务 选购监控 94", exact: true }).getByRole("button", { name: "重新采集", exact: true })).toBeVisible();
});

test("history and independent log rounds survive refresh and return to task details", async ({ page }) => {
  const fixture = await scenario(page);
  await page.goto("/projects/10?view=monitors");
  await page.getByRole("button", { name: "选购监控 94", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "选购监控 94 · 监控详情" });
  await expect(detail.getByText("搜索与运行规则", { exact: true })).toBeVisible();
  await detail.getByRole("button", { name: /MonitorRun #942/ }).click();
  await expect(page).toHaveURL(/run=942/);
  await expect(detail.locator('[aria-label="MonitorRun #942 详情"] .sp-status')).toHaveAttribute("data-kind", "inactive");
  await detail.getByRole("button", { name: "查看该任务采集日志", exact: true }).click();
  const logs = page.getByRole("dialog", { name: "选购监控 94 · 采集日志" });
  await expect(logs.getByText("从 MonitorRun #942 进入")).toBeVisible();
  await expect(logs.getByText(/尚无精确关联/)).toBeVisible();
  await logs.getByRole("combobox", { name: "日志采集轮次" }).selectOption(fixture.older);
  await expect(logs.getByRole("log")).toContainText("historical collection output");
  await page.reload();
  await expect(page.getByRole("log")).toContainText("historical collection output");
  await page.keyboard.press("Escape");
  await expect(detail).toBeVisible();
  await expect(detail.locator('[aria-label="MonitorRun #942 详情"]')).toBeVisible();
  expect(fixture.writes).toEqual([]);
});

test("existing control endpoints preserve pause, resume, stop and explicit rerun scopes", async ({ page }) => {
  const fixture = await scenario(page);
  await page.goto("/projects/10?view=monitors&monitor=93");
  let detail = page.getByRole("dialog", { name: "选购监控 93 · 监控详情" });
  await detail.getByRole("switch").click();
  await expect(detail.locator(".sp-execution .sp-status")).toHaveText("等待下一轮");
  await detail.getByRole("switch").click();
  await expect(detail.locator(".sp-execution .sp-status")).toHaveText("采集已暂停");
  await detail.getByRole("button", { name: "停止监控（含当前采集）", exact: true }).click();
  await expect(detail.locator(".sp-execution .sp-status")).toHaveText("监控已停止");
  await page.goto("/projects/10?view=monitors&monitor=94");
  detail = page.getByRole("dialog", { name: "选购监控 94 · 监控详情" });
  await detail.getByRole("button", { name: "重新采集", exact: true }).click();
  await expect(detail.locator(".sp-execution .sp-status")).toHaveText("等待下一轮");
  expect(fixture.writes.map(item => new URL(item.url).pathname)).toEqual([
    "/api/tasks/10/monitors/93/resume", "/api/tasks/10/monitors/93/pause", "/api/tasks/10/monitors/93/stop", "/api/projects/10/monitors/94/runs",
  ]);
});

test("editing retains preview and explicit revision confirmation without starting collection", async ({ page }) => {
  const fixture = await scenario(page);
  await page.goto("/projects/10?view=monitors&monitor=93");
  await page.getByRole("button", { name: "检查并编辑规则" }).click();
  const draft = page.getByRole("dialog", { name: "监控计划草案" });
  await draft.getByLabel("搜索关键词", { exact: true }).fill("MacBook Pro 16GB");
  await draft.getByRole("button", { name: "预览计划", exact: true }).click();
  expect(fixture.writes).toEqual([]);
  await draft.getByRole("button", { name: "明确确认永久变更", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "选购监控 93 · 监控详情" })).toContainText("MacBook Pro 16GB");
  expect(fixture.writes).toHaveLength(1);
  expect(fixture.writes[0].body).toMatchObject({ expected_revision: 7, confirmed: true, keyword: "MacBook Pro 16GB" });
});

test("failed refresh revokes cached live state and disables task controls", async ({ page }) => {
  const fixture = await scenario(page);
  await page.goto("/projects/10?view=monitors&monitor=91");
  const detail = page.getByRole("dialog", { name: "选购监控 91 · 监控详情" });
  await expect(detail.locator(".sp-execution .sp-status")).toHaveAttribute("data-kind", "running");
  fixture.fail();
  await expect(detail.locator(".sp-execution .sp-status")).toHaveAttribute("data-kind", "unknown", { timeout: 10_000 });
  await expect(detail.getByRole("switch")).toBeDisabled();
  expect(fixture.writes).toEqual([]);
});
