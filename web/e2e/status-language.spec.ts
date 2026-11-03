import { expect, test, type Page } from "@playwright/test";

// Controlled status responses belong exclusively to the isolated E2E server.
async function researchFixture(page: Page, options: { paused?: number; state?: string; underAI?: number; coverage?: Record<string, number>; total?: number } = {}) {
  let failed = false;
  await page.route("**/api/projects/10/overview", async route => {
    if (failed) return route.fulfill({ status: 503, json: { error: { code: "offline", message: "状态服务暂不可用" } } });
    const response = await route.fetch(); const data = await response.json(); delete data.goal_context; delete data.research_work;
    data.policy = { ...data.policy, paused: options.paused ?? 0, completed: 0, auto_research: 1 };
    data.project.status = "active";
    data.phase = "incremental";
    data.report = { id: 1, content: "隔离测试中的已保存报告", candidate_ids_json: "[]", snapshot_at: "2026-10-22T02:00:00Z", created_at: "2026-10-22T02:05:00Z", limited: 1 };
    data.coverage = { ...data.coverage, waiting: 2, under_ai: options.underAI ?? 0, evaluated: 7, ...options.coverage };
    if (options.total !== undefined) data.total = options.total;
    data.studies = options.state ? [{ id: 501, kind: "incremental", state: options.state, listing_ids: [1, 2], snapshot_at: "2026-10-22T02:00:00Z", created_at: "2026-10-22T02:00:00Z", finished_at: null, error: null, result: null }] : [];
    if (options.underAI) data.cards.forEach((card: { research_state: string }) => card.research_state = "queued");
    await route.fulfill({ json: data });
  });
  return { fail: () => { failed = true; } };
}

test("research statistics show three distinct product counts and disclose coverage on demand", async ({ page }, info) => {
  await researchFixture(page, { state: "running", underAI: 16, total: 116,
    coverage: { evaluated: 17, under_ai: 16, waiting: 1, summarized: 82, rule_excluded: 0, blocked: 0, needs_information: 0 } });
  const writes: string[] = [];
  page.on("request", request => { if (request.method() !== "GET") writes.push(request.url()); });
  await page.goto("/projects/10?view=research");
  const metrics = page.getByLabel("核心研究统计");
  await expect(metrics.locator(":scope > div")).toHaveCount(3);
  await expect(metrics).toHaveText("17已逐项分析16已安排研究1等待安排");
  await expect(page.getByText("另有 82 件仅有批次概述，尚无逐项评价。", { exact: true })).toBeVisible();
  const coverage = page.locator(".sp-research-coverage");
  await expect(coverage).not.toHaveAttribute("open", "");
  await expect(coverage.getByText("研究受阻", { exact: true })).toBeHidden();
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await page.getByRole("link", { name: "查看当前研究详情 →", exact: true }).click();
  await expect(page).toHaveURL(/#research-run-501$/);
  await expect(page.getByRole("heading", { name: "AgentRun #501 · 增量研究" })).toBeVisible();
  await coverage.getByText("研究覆盖详情", { exact: true }).click();
  await expect(coverage.getByText("研究受阻", { exact: true })).toBeVisible();
  await expect(coverage).toContainText("当前已返回记录中：1 个运行任务、0 个排队任务");
  expect(writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await coverage.getByText("研究覆盖详情", { exact: true }).click();
  await page.screenshot({ path: info.outputPath("research-three-metrics.png"), fullPage: true });
});

test("research uses compact shared Agent launchers before history and preserves monitor confirmation", async ({ page }) => {
  await researchFixture(page, { state: "completed" });
  const writes: string[] = [];
  page.on("request", request => { if (request.method() !== "GET") writes.push(request.url()); });
  await page.goto("/projects/10?view=research");
  const commands = page.getByLabel("研究操作", { exact: true });
  await expect(page.getByRole("textbox", { name: "给 Agent 的指令", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "新建监控", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "暂停研究调度", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "研究下一个有限批次", exact: true })).toBeVisible();
  expect(await commands.evaluate(node => !!(node.compareDocumentPosition(document.getElementById("research-run-501")!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  await commands.getByRole("button", { name: "本次研究重点", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "SecondPick Agent", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "打开历史对话与补抓", exact: true }).click();
  await expect(dialog.getByRole("region", { name: "持久化对话", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "收起项目对话", exact: true }).click();
  await dialog.getByRole("textbox", { name: "给 Agent 的指令", exact: true }).fill("以后只抓 16GB");
  await dialog.getByRole("button", { name: "提交本次研究", exact: true }).click();
  const draft = page.getByRole("dialog", { name: "监控计划草案", exact: true });
  await expect(draft).toBeVisible();
  await expect(draft.getByLabel("自然语言监控要求")).toHaveValue("以后只抓 16GB");
  expect(writes).toEqual([]);
  await draft.getByRole("button", { name: "关闭监控计划草案", exact: true }).click();
  await page.getByRole("link", { name: "返回 Agent 研究", exact: true }).click();
  await expect(commands).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
});

test("automatic research enabled and an existing report never imply a running task", async ({ page }, info) => {
  await researchFixture(page);
  await page.goto("/projects/10?view=research");
  await expect(page.getByText("自动研究已启用", { exact: true })).toHaveAttribute("data-kind", "ready");
  await expect(page.getByText("本项目研究当前空闲", { exact: true })).toHaveAttribute("data-kind", "waiting");
  await expect(page.locator('[data-kind="running"]')).toHaveCount(0);
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await page.goto("/projects/10");
  await expect(page.getByText("本项目研究当前空闲", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前研究判断" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("research-idle.png"), fullPage: true });
});

test("a paused scheduler and an executing AgentRun are presented independently", async ({ page }, info) => {
  await researchFixture(page, { paused: 1, state: "running", underAI: 2 });
  await page.goto("/projects/10?view=research");
  await expect(page.getByText("研究调度已暂停", { exact: true })).toHaveAttribute("data-kind", "paused");
  await expect(page.locator('.sp-execution [data-kind="running"]')).toHaveText("研究正在执行");
  await expect(page.getByRole("button", { name: "恢复研究调度" })).toBeVisible();
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await page.locator('.sp-execution [data-kind="running"] svg').evaluate(node => getComputedStyle(node).animationName)).toBe("none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("research-paused-with-active-run.png"), fullPage: true });
});

test("queued tasks and queued product coverage remain neutral", async ({ page }) => {
  await researchFixture(page, { state: "queued", underAI: 2 });
  await page.goto("/projects/10?view=research");
  await expect(page.getByText("等待研究任务执行", { exact: true })).toHaveAttribute("data-kind", "waiting");
  await expect(page.locator('[data-kind="running"]')).toHaveCount(0);
  await page.goto("/projects/10?view=products");
  await expect(page.getByText("已纳入研究任务", { exact: true }).first()).toHaveAttribute("data-kind", "waiting");
  await expect(page.locator('[data-kind="running"]')).toHaveCount(0);
});

test("a failed refresh revokes cached running badges immediately", async ({ page }) => {
  const scenario = await researchFixture(page, { state: "running", underAI: 2 });
  await page.goto("/projects/10?view=research");
  await expect(page.locator('.sp-execution [data-kind="running"]')).toBeVisible();
  scenario.fail();
  // Other projects and monitor sources load independently; wait for this research source to fail.
  await expect(page.locator("main .sp-execution").getByText("状态暂不可确认", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('[data-kind="running"]')).toHaveCount(0);
});

test("running execution windows do not cause waiting collectors to animate", async ({ page }, info) => {
  let state = "waiting";
  await page.route("**/api/projects/10/monitors", route => route.fulfill({ json: { items: [{ monitor_id: 91, name: "状态验收监控", mode: "ongoing", duration_seconds: null, revision: 0,
    monitor: { id: 91, task_id: 10, state, desired_state: null, keyword: "测试关键词", rounds: 2, imported: 3, max_rounds: 1000, max_pages: 3, max_items: 50,
      interval_seconds: 1800, collect_seller_profiles: false, next_run_at: "2026-10-22T12:00:00Z", updated_at: "2026-10-22T02:00:00Z", error_code: state === "needs_attention" ? "verification_required" : null,
      result: { worker_status: { phase: "collecting", error_code: null } } },
    runs: [{ id: 3, state: "running", started_at: "2026-10-22T02:00:00Z", finished_at: null, deadline_at: null, error: null }] }] } }));
  await page.route("**/monitors/91/events?*", route => route.fulfill({ json: { items: [], has_more: false, next_before_id: null } }));
  await page.goto("/projects/10?view=monitors");
  await expect(page.getByText("监控调度已启用", { exact: true })).toHaveAttribute("data-kind", "ready");
  await expect(page.getByText("等待下一轮", { exact: true })).toHaveAttribute("data-kind", "waiting");
  await expect(page.locator('[data-kind="running"]')).toHaveCount(0);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  state = "running";
  await expect(page.locator('.sp-execution .sp-status')).toHaveText("正在采集", { timeout: 7000 });
  await expect(page.locator('.sp-execution .sp-status')).toHaveAttribute("data-kind", "running");
  await expect(page.getByRole("button", { name: "停止监控（含当前采集）" })).toBeVisible();
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  state = "needs_attention";
  await expect(page.locator(".sp-execution .sp-status")).toHaveAttribute("data-kind", "attention", { timeout: 7000 });
  await expect(page.locator('[data-kind="running"]')).toHaveCount(0);
  expect(await page.locator(".sp-execution .sp-status").evaluate(node => getComputedStyle(node).color)).toBe("rgb(189, 64, 68)");
  await page.screenshot({ path: info.outputPath("monitor-attention.png"), fullPage: true });
});
