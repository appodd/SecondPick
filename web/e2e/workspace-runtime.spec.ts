import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page, count = 2) {
  const template = await (await page.request.get("/api/projects/10/overview")).json();
  let failed = false, due = false, paused = false;
  const names = ["选购二手 MacBook Pro", "选购适合 CAD 的二手 iMac"];
  const tasks = Array.from({ length: count }, (_, i) => ({ id: i + 1, title: names[i] ?? (i === 19 ? "适合专业设计和多种复杂工作场景的超长选购项目名称与配置说明" : `项目 ${i + 1}`), city: "上海", status: "active", run_count: 0, report_count: 0, updated_at: "2026-10-22T00:00:00Z" }));
  await page.route("**/api/tasks?*", route => {
    const params = new URL(route.request().url()).searchParams, offset = Number(params.get("offset") ?? 0), limit = Number(params.get("limit") ?? 100);
    return route.fulfill({ json: { items: tasks.slice(offset, offset + limit), total_count: count, returned_count: Math.min(count - offset, limit), truncated: offset + limit < count, page: { offset, limit, has_more: offset + limit < count, next_offset: offset + limit < count ? offset + limit : null } } });
  });
  await page.route(/\/api\/tasks\/\d+\/monitors$/, route => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    if (failed && id === 1) return route.fulfill({ status: 503, json: { detail: "unavailable" } });
    return route.fulfill({ json: { enabled: true, platform_enabled: true, candidate_pool_count: 0, items: id > 2 ? [] : [{ id, task_id: id,
      keyword: id === 1 ? "MacBook Pro M" : "imac", state: id === 2 ? "running" : paused ? "paused" : "waiting", desired_state: null, rounds: 1, imported: 0,
      max_rounds: 100, max_pages: 3, max_items: 50, interval_seconds: 1800, collect_seller_profiles: false, error_code: null,
      updated_at: new Date().toISOString(), next_run_at: new Date(Date.now() + (due ? -3600000 : 3600000)).toISOString(), result: { worker_status: { phase: "collecting", error_code: null } } }] } });
  });
  await page.route(/\/api\/projects\/\d+\/overview$/, route => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    if (failed && id === 1) return route.fulfill({ status: 503, json: { detail: "unavailable" } });
    return route.fulfill({ json: { ...template, project: { ...template.project, id, title: tasks[id - 1]?.title, status: "active" }, cards: [], total: 0, eligible: 0, report: null,
      studies: id === 2 ? [{ id: 22, kind: "incremental", state: "running", listing_ids: [], snapshot_at: new Date().toISOString(), created_at: new Date().toISOString(), finished_at: null, error: null, result: null }] : [],
      phase: "collecting_baseline", policy: { ...template.policy, auto_research: 1, paused: paused && id === 1 ? 1 : 0, completed: 0 }, coverage: { ...template.coverage, under_ai: 0 } } });
  });
  const writes: string[] = []; page.on("request", request => { if (request.method() !== "GET") writes.push(request.url()); });
  return { writes, fail: () => { failed = true; }, due: () => { due = true; }, pause: () => { paused = true; } };
}
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: "wait" }); });

test("cross-project sidebar and workspace view distinguish enabled, waiting, collection and research", async ({ page }, info) => {
  const data = await fixture(page);
  await page.goto("/projects/1");
  const first = page.locator('[data-runtime-project="1"]'), second = page.locator('[data-runtime-project="2"]');
  await expect(first).toContainText("采集等待"); await expect(first).toContainText("AI 空闲");
  await expect(second).toContainText("采集中"); await expect(second).toContainText("AI 研究中");
  await page.getByRole("button", { name: "运行中心", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "工作空间运行概况", exact: true });
  const macSection = dialog.locator('[aria-label="选购二手 MacBook Pro 运行概况"]');
  await expect(macSection).toContainText("1 个监控调度配置启用");
  await expect(macSection).toContainText("等待计划时间（按本机时钟）");
  await expect(dialog.locator('[aria-label="选购适合 CAD 的二手 iMac 运行概况"]')).toContainText("AgentRun #22");
  await expect(dialog.getByText("正在等待 iMac 本轮采集结束", { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("log")).toHaveCount(0);
  await dialog.getByRole("link", { name: "监控 #2 · imac", exact: true }).click();
  await expect(page).toHaveURL(/projects\/2\?view=monitors&monitor=2/);
  await expect(page.locator('[data-runtime-project="1"]')).toContainText("采集等待");
  await page.keyboard.press("Escape");
  expect(data.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.getByRole("link", { name: "返回运行中心", exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("link", { name: "AgentRun #22", exact: true }).click();
  await expect(page).toHaveURL(/projects\/2\?.*#research-run-22$/);
  await expect(page.getByRole("heading", { name: "研究 #22 · 增量研究", exact: true })).toBeInViewport();
  await page.getByRole("link", { name: "返回运行中心", exact: true }).click();
  await expect(dialog).toBeVisible();
  expect(data.writes).toEqual([]);
  await page.screenshot({ path: info.outputPath("workspace-runtime.png") });
});

test("a due plan never becomes a claimed resource wait and pause does not invent user intent", async ({ page }) => {
  const data = await fixture(page); data.due();
  await page.goto("/projects/1?runtime=1");
  const mac = page.getByRole("dialog", { name: "工作空间运行概况", exact: true }).locator('[aria-label="选购二手 MacBook Pro 运行概况"]');
  await expect(mac).toContainText("计划时间已到，等待后端调度");
  await expect(mac).toContainText("具体资源等待原因未提供");
  data.pause(); await page.reload();
  await expect(mac).toContainText("采集已暂停");
  await expect(page.locator('[data-runtime-project="1"]')).toContainText("AI 暂停");
  expect(data.writes).toEqual([]);
});

test("one project's failed refresh cannot revoke another project's confirmed running state", async ({ page }) => {
  const data = await fixture(page);
  await page.goto("/projects/2");
  await expect(page.locator('[data-runtime-project="1"]')).toContainText("采集等待");
  data.fail();
  await expect(page.locator('[data-runtime-project="1"] .sp-status').first()).toHaveAttribute("data-kind", "unknown", { timeout: 12000 });
  await expect(page.locator('[data-runtime-project="2"] .sp-status').first()).toHaveAttribute("data-kind", "running");
  expect(data.writes).toEqual([]);
});

test("workspace projects are paginated with explicit scope and links survive page refresh", async ({ page }) => {
  const data = await fixture(page, 10);
  await page.goto("/projects/1?runtime=1");
  const dialog = page.getByRole("dialog", { name: "工作空间运行概况", exact: true });
  await expect(dialog.getByText("第 1 页 · 本页 8 个项目 · 共 10 个项目", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "下一页项目", exact: true }).click();
  await expect(dialog.getByText("第 2 页 · 本页 2 个项目 · 共 10 个项目", { exact: true })).toBeVisible();
  await page.reload(); await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape"); await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "运行中心", exact: true })).toBeFocused();
  expect(data.writes).toEqual([]);
});

test("sidebar keeps fixed entries visible with one, two, five, ten and twenty projects across window heights", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "Desktop rail; narrow layout is covered by project navigation tests.");
  test.setTimeout(60000);
  for (const count of [1, 2, 5, 10, 20]) {
    const data = await fixture(page, count);
    await page.goto("/projects/1");
    const list = page.getByRole("region", { name: "选购项目列表", exact: true });
    while (await list.getByRole("button", { name: /显示更多项目/ }).count()) await list.getByRole("button", { name: /显示更多项目/ }).click();
    await expect(list.locator("a[data-runtime-project]")).toHaveCount(count);
    for (const height of [1000, 820, 720, 640]) {
      await page.setViewportSize({ width: 1440, height });
      for (const entry of [page.getByRole("button", { name: "新建选购项目", exact: true }), page.getByRole("button", { name: "运行中心", exact: true }), page.getByRole("button", { name: "Agent 研究", exact: true }), page.locator(".ss-sidebar-bottom").getByRole("link", { name: "设置", exact: true })]) {
        await expect(entry).toBeInViewport();
      }
      expect(await page.locator(".sp-side").evaluate(node => node.scrollHeight <= node.clientHeight + 1)).toBe(true);
      expect(await list.evaluate(node => node.clientHeight)).toBeGreaterThan(30);
      const gap = await page.locator(".sp-project-region").evaluate(node => node.nextElementSibling!.getBoundingClientRect().top - node.getBoundingClientRect().bottom);
      expect(gap).toBeLessThan(25);
      if (count <= 2 && height === 1000) {
        expect(await list.evaluate(node => node.scrollHeight - node.clientHeight)).toBeLessThanOrEqual(1);
        const space = await page.locator(".ss-sidebar-bottom").evaluate(node => node.getBoundingClientRect().top - node.previousElementSibling!.getBoundingClientRect().bottom);
        expect(space).toBeGreaterThan(80);
      }
    }
    await page.setViewportSize({ width: 1440, height: 480 });
    const settings = page.locator(".ss-sidebar-bottom").getByRole("link", { name: "设置", exact: true });
    await settings.focus(); await expect(settings).toBeInViewport();
    await expect(page.getByRole("button", { name: "新建选购项目", exact: true })).toBeInViewport();
    await page.getByRole("button", { name: "研究概览", exact: true }).focus();
    await expect(page.getByRole("button", { name: "研究概览", exact: true })).toBeInViewport();
    expect(data.writes).toEqual([]);
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("project list supports wheel and keyboard, reveals changed selection, and preserves scroll across polling", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "Desktop project list has a mobile select alternative.");
  const data = await fixture(page, 20);
  await page.setViewportSize({ width: 1440, height: 720 });
  await page.goto("/projects/1");
  const list = page.getByRole("region", { name: "选购项目列表", exact: true });
  while (await list.getByRole("button", { name: /显示更多项目/ }).count()) await list.getByRole("button", { name: /显示更多项目/ }).click();
  await list.evaluate(node => { node.scrollTop = 0; });
  await list.hover(); await page.mouse.wheel(0, 300);
  await expect.poll(() => list.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
  expect(await page.locator(".sp-side").evaluate(node => node.scrollTop)).toBe(0);
  await list.focus(); await page.keyboard.press("End");
  await expect(list.locator('[data-runtime-project="20"]')).toBeInViewport();
  const title = list.locator('[data-runtime-project="20"] strong');
  expect(await title.evaluate(node => node.scrollWidth > node.clientWidth && getComputedStyle(node).textOverflow === "ellipsis")).toBe(true);
  await expect(title).toHaveAttribute("title", /超长选购项目/);
  await expect(list.locator('[data-runtime-project="20"] .sp-status')).toHaveCount(2);
  await list.locator('[data-runtime-project="20"]').click();
  await expect(page).toHaveURL(/projects\/20$/);
  await expect(list.locator('[data-runtime-project="20"]')).toBeInViewport();
  await list.evaluate(node => { node.scrollTop = 100; });
  const scroll = await list.evaluate(node => node.scrollTop);
  await page.waitForResponse(response => response.url().endsWith("/api/tasks/20/monitors"));
  expect(await list.evaluate(node => node.scrollTop)).toBe(scroll);
  await page.goBack();
  await expect(list.locator('[data-runtime-project="1"]')).toBeInViewport();
  expect(data.writes).toEqual([]);
});
