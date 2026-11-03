import { expect, test, type Page } from "@playwright/test";

async function prepare(page: Page, keyword: string) {
  await page.goto("/settings?section=xianyu");
  await page.getByRole("button", { name: /打开.*登录窗口/ }).click();
  await expect(page.getByRole("button", { name: "我已登录，验证连接" })).toBeEnabled();
  await page.getByRole("button", { name: "我已登录，验证连接" }).click();
  await expect(page.locator(".ss-panel-title .ss-badge")).toHaveText("已验证");
  await page.goto("/new");
  await page.getByRole("textbox", { name: "对话输入" }).fill("找一只 NS2 Pro 手柄");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("tab", { name: "监控", exact: true }).click();
  await page.getByRole("textbox", { name: "监控关键词" }).fill(keyword);
  const start = page.getByRole("button", { name: "确认范围并启动监控" });
  await expect(start).toBeDisabled();
  await page.getByRole("checkbox", { name: /我已确认以上范围/ }).check();
  await start.click();
  await expect(page.locator(".monitor-pool strong")).toHaveText("30");
}

test("monitor scope runs, keeps a larger pool, pauses, resumes and stops across reloads", async ({ page }, info) => {
  await prepare(page, "离线 NS2 Pro");
  const card = page.getByRole("article", { name: /监控 离线 NS2 Pro/ });
  await expect(card.locator(".sp-status").filter({ hasText: /^正在采集$/ })).toBeVisible();
  await expect(card.locator(".monitor-metrics")).toContainText("商品记录2");
  await expect(card.locator(".monitor-metrics")).toContainText("搜索卡片30");
  await page.reload();
  await expect(page.locator(".monitor-pool strong")).toHaveText("30");
  await card.getByRole("button", { name: "暂停监控" }).click();
  await expect(card.getByText("采集已暂停", { exact: true })).toBeVisible();
  await page.reload();
  await card.getByRole("button", { name: "恢复原范围" }).click();
  await expect(card.locator(".sp-status").filter({ hasText: /^正在采集$/ })).toBeVisible();
  await card.getByRole("button", { name: "停止监控" }).click();
  await expect(card.getByText("监控已停止", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "查看运行记录" }).click();
  await expect(card.getByText(/开始本轮采集/).first()).toBeVisible();
  await expect(card.getByRole("button", { name: "恢复原范围" })).toHaveCount(0);
  await page.reload();
  await card.getByRole("button", { name: "继续原监控" }).click();
  await expect(card.locator(".sp-status").filter({ hasText: /^正在采集$/ })).toBeVisible();
  await expect(page.getByRole("article", { name: /监控 离线 NS2 Pro/ })).toHaveCount(1);
  await expect(page.locator(".monitor-pool strong")).toHaveText("30");
  await card.getByRole("button", { name: "停止监控" }).click();
  await expect(card.getByText("监控已停止", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("monitor-stopped.png"), fullPage: true });
  await page.getByRole("link", { name: "查看全部候选", exact: true }).click();
  await expect(page.getByRole("tab", { name: "全部候选" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("离线监控手柄 1", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "对话", exact: true }).click();
  await page.getByRole("textbox", { name: "对话输入" }).fill("根据已有商品筛选");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".conversation-item--assistant")).toHaveCount(2);
});

test("timeout preserves candidates, exposes reasons and diagnostic history", async ({ page }, info) => {
  await prepare(page, "超时 NS2 Pro");
  const card = page.getByRole("article", { name: /监控 超时 NS2 Pro/ });
  await expect(card.getByText("采集需要处理", { exact: true })).toBeVisible();
  await expect(card.getByText(/本轮采集超时/)).toBeVisible();
  await page.reload();
  await expect(page.locator(".monitor-pool strong")).toHaveText("30");
  await card.getByRole("button", { name: "查看运行记录" }).click();
  await expect(card.locator(".monitor-diagnostics")).toContainText("本轮采集超时");
  await page.screenshot({ path: info.outputPath("monitor-timeout.png"), fullPage: true });
  await card.getByRole("button", { name: "停止监控" }).click();
  await expect(card.getByRole("button", { name: "继续原监控" })).toBeVisible();
  await expect(card.getByText("采集需要处理", { exact: true })).toBeVisible();
});

test("failed latest attempt keeps cumulative data clearly visible", async ({ page }, info) => {
  await prepare(page, "超时 NS2 Pro");
  await page.route("**/api/tasks/*/monitors", async route => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const data = await response.json();
    data.candidate_pool_count = 158;
    data.items = data.items.map((m: Record<string, unknown>) => ({ ...m, state: "needs_attention", rounds: 3,
      imported: 169, error_code: "login_required", result: { imported: 0 } }));
    await route.fulfill({ json: data });
  });
  await page.reload();
  const card = page.getByRole("article", { name: /监控 超时 NS2 Pro/ });
  await expect(card.getByLabel("累计保留的数据")).toContainText("本监控累计商品记录169");
  await expect(card.getByLabel("累计保留的数据")).toContainText("当前任务去重候选（含其他来源）158");
  await expect(card.getByLabel("最近一轮同步记录")).toContainText("商品记录0搜索卡片—报价观察—");
  await expect(card.getByText(/已尝试 3 \/ 24 轮 · 剩余 21 轮/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await card.screenshot({ path: info.outputPath("monitor-cumulative-retained.png") });
});

test("environment check explains readiness and prevents starting after failure", async ({ page }, info) => {
  await page.route("**/api/monitor-engine/check", route => route.fulfill({ json:
    route.request().method() === "POST"
      ? { ready: false, checked_at: "2026-10-20T09:00:00Z", checks: [{ code: "dependencies", ok: true }, { code: "browser", ok: false }] }
      : { result: null } }));
  await page.goto("/new");
  await page.getByRole("textbox", { name: "对话输入" }).fill("环境检查手柄任务");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("tab", { name: "监控", exact: true }).click();
  await page.getByRole("textbox", { name: "监控关键词" }).fill("NS2 Pro");
  await page.getByRole("checkbox", { name: /我已确认以上范围/ }).check();
  await expect(page.getByRole("button", { name: "确认范围并启动监控" })).toBeEnabled();
  await page.getByRole("button", { name: "检查采集环境" }).click();
  await expect(page.getByText("无头浏览器：未通过")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认范围并启动监控" })).toBeDisabled();
  await expect(page.getByText(/暂无监控/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("monitor-environment.png"), fullPage: true });
});

test("live console refreshes filtered text and supports earlier pages", async ({ page }, info) => {
  let reads = 0;
  await page.route("**/monitors/*/logs?*", async route => {
    reads++;
    const older = new URL(route.request().url()).searchParams.has("before");
    await route.fulfill({ json: {
      items: [{ at: "2026-10-20T09:00:00Z", text: older ? "earlier page output" : reads > 1 ? "page 2: processing next item" : "page 1: waiting 5 seconds" },
        { at: "2026-10-20T09:00:01Z", text: '<img src=x onerror="window.__consoleInjected=1">' }],
      rounds: [{ id: "a".repeat(32), updated_at: "2026-10-20T09:00:00Z" }], round_id: "a".repeat(32),
      next_before: older ? null : 100, has_more: !older, capture_enabled: true, max_bytes: 4194304, max_rounds: 5,
    } });
  });
  await prepare(page, "日志 NS2 Pro");
  const card = page.getByRole("article", { name: /监控 日志 NS2 Pro/ });
  await card.getByRole("button", { name: "查看采集日志" }).click();
  await expect(card.getByRole("log")).toContainText("page 2: processing next item");
  await expect(card.getByRole("log").locator("img")).toHaveCount(0);
  await card.getByRole("button", { name: "查看更早日志" }).click();
  await expect(card.getByRole("log")).toContainText("earlier page output");
  await card.getByRole("button", { name: "回到最新日志" }).click();
  await expect(card.getByRole("log")).toContainText("page 2");
  await page.screenshot({ path: info.outputPath("monitor-console.png"), fullPage: true });
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).__consoleInjected)).toBeUndefined();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await card.getByRole("button", { name: "停止监控" }).click();
  await expect(card.getByText("监控已停止", { exact: true })).toBeVisible();
});
