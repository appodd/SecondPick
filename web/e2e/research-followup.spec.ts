import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page, failed = false) {
  await page.route("**/api/projects/10/overview", async route => {
    const data = await (await route.fetch()).json();
    data.goal_context = { ...data.goal_context, current_revision: 1, report_current: true, calibration: "current", legacy_unmerged: false };
    data.policy = { ...data.policy, auto_research: 1, paused: 0, completed: 0 };
    data.coverage = { evaluated: 12, summarized: failed ? 83 : 87, blocked: failed ? 4 : 0, waiting: 0, needs_information: 0, under_ai: 0, rule_excluded: 0 };
    data.total = 99; data.phase = "incremental";
    data.report = { id: 47, study_id: 49, goal_revision: 1, content: "隔离测试的有限报告", candidate_ids_json: "[]", snapshot_at: "2026-10-23", created_at: "2026-10-23", limited: 1 };
    data.studies = failed ? [{ id: 50, kind: "followup", goal_revision: 1, state: "failed", listing_ids: [1879, 1881, 1887, 1889], snapshot_at: "2026-10-23", created_at: "2026-10-23", finished_at: "2026-10-23", error: "补研未返回完整、有效的逐项结构化判断；已保留输出，不自动重试同目标同证据。", result: { content: "模拟纯摘要，不视为逐项研究", candidate_ids: [] } }] : [];
    data.research_work = { goal_revision: 1, total: 99, unassessed: 87, batch_limit: 10, quota: "unknown", gate: failed ? "idle" : "ready",
      reason: failed ? "当前没有可自动安排的补研样本；不代表剩余商品没有研究价值" : "有明确补研线索，可按现有批次上限安排；不自动研究全部未分析商品",
      counts: { evaluated: 12, ready: failed ? 0 : 4, needs_evidence: 83, no_priority: 0, attempted: 0, failed: failed ? 4 : 0, queued: 0, running: 0, rule_excluded: 0 }, listing_ids: failed ? [] : [1879, 1881, 1887, 1889],
      items: [{ listing_id: 1879, state: failed ? "failed" : "ready", reason: failed ? "补研失败，可在原任务手动重试" : "历史研究曾提名（不是当前推荐结论）；已有标题与有效挂牌价，可有限核对", study_id: failed ? 50 : null }] };
    await route.fulfill({ json: data });
  });
}

test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "wait" }));

test("coverage distinguishes completed, unassessed, valuable followup and missing evidence", async ({ page }, info) => {
  await fixture(page);
  await page.goto("/projects/10?view=research");
  const stats = page.getByLabel("核心研究统计");
  await expect(stats).toContainText("12已逐项分析");
  await expect(stats).toContainText("87尚未逐项研究");
  const work = page.getByLabel("后续研究安排");
  await expect(work).toContainText("可有限补研 4 件");
  await expect(work).toContainText("需补证据或指定重点 83 件");
  await expect(work).toContainText("账号剩余额度暂不可确认");
  await page.getByText("研究覆盖详情", { exact: true }).click();
  await page.getByText("查看选样与跳过原因", { exact: true }).click();
  await expect(page.getByText(/#1879：历史研究曾提名/)).toBeVisible();
  if (info.project.name.startsWith("mobile")) expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: info.outputPath("research-followup.png"), fullPage: true });
  await page.reload();
  await expect(page.getByLabel("后续研究安排")).toContainText("可有限补研 4 件");
});

test("summary-only failure is visible, keeps saved output and offers original-snapshot retry", async ({ page }) => {
  await fixture(page, true);
  let retries = 0;
  await page.route("**/api/projects/10/studies/50/retry", async route => { retries++; await route.fulfill({ json: { id: 50 } }); });
  await page.goto("/projects/10?view=research");
  await expect(page.getByText("有限补研需要处理", { exact: true })).toBeVisible();
  await expect(page.getByText(/补研未返回完整、有效的逐项结构化判断/)).toBeVisible();
  const retry = page.getByRole("button", { name: "重试原快照", exact: true });
  await retry.click();
  await expect.poll(() => retries).toBe(1);
  await page.getByText("研究结论与依据", { exact: true }).click();
  await expect(page.getByText("模拟纯摘要，不视为逐项研究", { exact: true })).toBeVisible();
  await expect(page.getByLabel("核心研究统计")).toContainText("12已逐项分析");
});
