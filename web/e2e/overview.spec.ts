import { expect, test, type Page } from "@playwright/test";

// These controlled results exist only in the isolated temporary fixture service.
async function overviewFixture(page: Page, options: { noReport?: boolean; running?: boolean; paused?: boolean; narrative?: boolean } = {}) {
  let version = 1;
  let monitorState = options.paused ? "paused" : "waiting";
  let failMonitor = false;
  await page.route("**/api/tasks/10/monitors", route => route.fulfill(failMonitor ? { status: 503, json: { detail: "unavailable" } } : { json: {
    enabled: true, platform_enabled: true, candidate_pool_count: 35,
    items: [{ id: 101, task_id: 10, state: monitorState, desired_state: null, error_code: null, result: {}, next_run_at: null, updated_at: "2026-10-22T02:00:00Z" }],
  } }));
  await page.route("**/api/projects/10/overview", async route => {
    const response = await route.fetch({ maxRetries: 2 }); const data = await response.json(); delete data.goal_context; const id = data.cards[0].listing_id;
    const content = options.narrative ? "一段没有明确综合结论的长报告。\n\n保留原文供查看。" : `## 综合结论\n\n建议先核实机器状态，再确定交易对象。\n\n## 完整原文\n\n${"本段是完整报告原文，包含保存证据及其局限。".repeat(120)}\n\n报告版本 ${version} 的结尾。`;
    data.policy = { ...data.policy, auto_research: 1, paused: 0, completed: 0 };
    data.project.status = "active"; data.phase = options.noReport ? "collecting_baseline" : "incremental";
    data.total = 35; data.eligible = 8;
    data.coverage = { rule_excluded: 10, waiting: 5, needs_information: 2, under_ai: 0, evaluated: 7, summarized: 11, blocked: 0 };
    data.changes = [{ id: 1, content: "已保存的候选变化", created_at: "2026-10-22T02:10:00Z" }];
    data.report = options.noReport ? null : { id: version, study_id: 40, content, candidate_ids_json: JSON.stringify([id]), snapshot_at: "2026-10-22T01:00:00Z", created_at: "2026-10-22T02:00:00Z", limited: 1 };
    data.studies = options.noReport ? [] : [{ id: 40, kind: "initial", state: "completed", listing_ids: [id], snapshot_at: "2026-10-22T01:00:00Z", finished_at: "2026-10-22T02:00:00Z", created_at: "2026-10-22T01:00:00Z", error: null,
      result: { content, candidate_ids: [id], research: options.narrative ? null : { criteria: [{ criterion_id: "repair", description: "维修情况", priority: "hard", source_refs: ["task_goal"], source_message_ids: [] }],
        assessments: [{ listing_id: id, conclusion: "conditional", summary: "配置描述值得继续核对，尚不能直接下单。", judgments: [{ criterion_id: "repair", status: "UNKNOWN", source_type: "missing", reason: "维修记录与实物情况仍待核实", evidence_refs: [] }] }] } } }];
    if (options.running) { data.studies.unshift({ id: 41, kind: "incremental", state: "running", listing_ids: [id], snapshot_at: "2026-10-22T03:00:00Z", created_at: "2026-10-22T03:00:00Z", result: null, error: null }); data.coverage.under_ai = 1; }
    await route.fulfill({ json: data });
  });
  return { update: () => { version++; }, monitor: (state: string) => { monitorState = state; }, failMonitor: () => { failMonitor = true; } };
}

test("overview monitor and research drill-downs share the contextual return without changing sidebar navigation", async ({ page }) => {
  await overviewFixture(page);
  await page.goto("/projects/10?view=overview");
  for (const name of ["监控采集 ↗", "Agent 研究 ↗", "查看覆盖与研究状态 →"]) {
    await page.locator("summary").filter({hasText:"运行详情"}).click();
    await page.getByRole("button", { name, exact: true }).click();
    await page.getByRole("link", { name: "返回研究概览", exact: true }).click();
    await expect(page.getByRole("heading", { name: "目前，应该怎样选？", exact: true })).toBeVisible();
  }
});

test("overview quotes real conclusions and per-item findings while the full report has a separate reader", async ({ page }, info) => {
  const writes: string[] = []; page.on("request", request => { if (request.url().includes("/api/") && request.method() !== "GET") writes.push(request.url()); });
  await overviewFixture(page); await page.goto("/projects/10");
  const current = page.locator(".sp-current-report");
  await page.locator("summary").filter({hasText:"运行详情"}).click();
  await expect(current.getByText("建议先核实机器状态，再确定交易对象。", { exact: true })).toBeVisible();
  await expect(page.getByText("配置描述值得继续核对，尚不能直接下单。", { exact: true })).toBeVisible();
  await expect(page.locator(".sp-overview-concerns").getByText("维修记录与实物情况仍待核实", { exact: true })).toBeVisible();
  await expect(current.getByText(/报告版本 1 的结尾/)).toHaveCount(0);
  const metrics = page.getByRole("region", { name: "项目运行概况" });
  await expect(metrics.getByText("等待下一轮", { exact: true })).toHaveAttribute("data-kind", "waiting");
  await expect(metrics.getByText("本项目研究当前空闲", { exact: true })).toHaveAttribute("data-kind", "waiting");
  await expect(metrics.getByText("35", { exact: true })).toBeVisible(); await expect(metrics.getByText("7", { exact: true })).toBeVisible();
  await expect(metrics.getByText(/11 件仅批次概述/)).toBeVisible();
  expect(await current.evaluate(node => getComputedStyle(node).overflowY)).not.toMatch(/auto|scroll/);
  await current.getByRole("button", { name: "阅读完整报告" }).click();
  const reader = page.getByRole("dialog", { name: "完整研究报告" });
  await expect(reader.getByText("报告版本 1 的结尾。", { exact: true })).toBeVisible();
  expect(await reader.locator(".sp-report-content").first().evaluate(node => getComputedStyle(node).overflowY)).toBe("visible");
  await page.keyboard.press("Escape"); await expect(reader).toHaveCount(0);
  await page.locator(".sp-overview-product").first().click(); await expect(page.getByRole("dialog", { name: "商品与卖家证据" })).toBeVisible();
  await page.keyboard.press("Escape");
  expect(writes).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("overview-compact.png"), fullPage: true });
});

test("no-report, active research, waiting collection and paused collection remain distinct", async ({ page }) => {
  const scenario = await overviewFixture(page, { noReport: true, running: true, paused: true });
  await page.goto("/projects/10");
  await page.locator("summary").filter({hasText:"运行详情"}).click();
  const metrics = page.getByRole("region", { name: "项目运行概况" });
  await expect(metrics.getByText("研究正在执行", { exact: true })).toHaveAttribute("data-kind", "running");
  await expect(metrics.getByText("采集已暂停", { exact: true })).toHaveAttribute("data-kind", "paused");
  await expect(page.getByRole("heading",{name:"正在进行首轮研究",exact:true})).toBeVisible();
  await expect(page.getByRole("button", { name: "阅读完整报告" })).toHaveCount(0);
  await expect(page.locator(".sp-overview-product")).toHaveCount(0);
  scenario.monitor("running"); await expect(metrics.getByText("正在采集", { exact: true })).toHaveAttribute("data-kind", "running", { timeout: 8000 });
  scenario.monitor("waiting"); await expect(metrics.getByText("等待下一轮", { exact: true })).toHaveAttribute("data-kind", "waiting", { timeout: 8000 });
  scenario.failMonitor(); await expect(metrics.getByText("状态暂不可确认", { exact: true })).toBeVisible({ timeout: 8000 });
});

test("missing narrative summary is explicit and unrelated short answers never become report conclusions", async ({ page }) => {
  await overviewFixture(page, { narrative: true }); await page.goto("/projects/10");
  await expect(page.getByText("报告开篇原文",{exact:true})).toBeVisible();
  await expect(page.locator(".sp-overview-conclusion")).toHaveText("一段没有明确综合结论的长报告。");
  await expect(page.getByText(/尚无可归属的逐项推荐理由/)).toBeVisible();
  await page.locator(".sp-overview-candidate summary").first().click();
  await expect(page.getByText("本批没有有效逐项判断。",{exact:true})).toBeVisible();
});

test("report polling keeps an open version and its scroll position stable", async ({ page }) => {
  const scenario = await overviewFixture(page); await page.goto("/projects/10");
  await page.getByRole("button", { name: "阅读完整报告" }).click();
  const reader = page.getByRole("dialog", { name: "完整研究报告" });
  await reader.locator(".responsive-drawer__content").evaluate(node => { node.scrollTop = 180; });
  const top = await reader.locator(".responsive-drawer__content").evaluate(node => node.scrollTop);
  scenario.update();
  await expect(reader.getByText(/已有新报告，当前阅读位置和原文保持不变/)).toBeVisible({ timeout: 8000 });
  await expect(reader.getByRole("heading", { name: "研究报告 #1", exact: true })).toBeVisible();
  expect(await reader.locator(".responsive-drawer__content").evaluate(node => node.scrollTop)).toBe(top);
  await reader.getByRole("button", { name: "阅读最新报告" }).click();
  await expect(reader.getByRole("heading", { name: "研究报告 #2", exact: true })).toBeVisible();
});
