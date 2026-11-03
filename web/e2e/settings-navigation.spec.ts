import { expect, test, type Page } from "@playwright/test";

test("technical default city is explained and legacy city requires confirmation without creating a condition", async ({ page }) => {
  await page.goto("/settings?section=diagnostics");
  await expect(page.getByText("此为兼容旧工具的技术配置，不代表项目交易地区偏好，也不限定监控采集地区。", { exact: true })).toBeVisible();
  await page.route("**/api/projects/10/overview", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), region_preference: { mode: "none", city: null, legacy_city: "上海", legacy_unverified: true } } });
  });
  await page.goto("/projects/10?view=overview");
  await expect(page.getByRole("note")).toContainText("来源待确认");
  await page.getByRole("button", { name: "调整选购条件", exact: true }).click();
  await expect(page.getByText(/历史城市记录为「上海」/)).toBeVisible();
  await expect(page.getByRole("textbox", { name: "保留的硬条件（每行一项）", exact: true })).not.toHaveValue(/上海/);
  await expect(page.getByRole("textbox", { name: "软偏好（每行一项）", exact: true })).not.toHaveValue(/上海/);
});

async function manyProjects(page: Page, count: number) {
  const template = await (await page.request.get("/api/projects/10/overview")).json();
  const tasks = Array.from({ length: count }, (_, i) => ({ id: i + 1, title: `选购项目 ${i + 1} · 足够长的商品需求说明用于验证截断`, city: "上海", status: "active", run_count: 0, report_count: 0 }));
  await page.route("**/api/tasks?*", route => route.fulfill({ json: { items: tasks, total_count: count, returned_count: count, truncated: false, page: { offset: 0, limit: 100, has_more: false, next_offset: null } } }));
  await page.route(/\/api\/projects\/\d+\/overview$/, route => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    return route.fulfill({ json: { ...template, project: { ...template.project, id, title: tasks[id-1]?.title } } });
  });
}
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "wait" }));

test("settings preserves the mounted workspace rail, selected project, source and single settings entry", async ({ page }, info) => {
  const writes: string[] = [];
  page.on("request", request => { if (!["GET", "HEAD"].includes(request.method())) writes.push(request.url()); });
  await page.goto("/projects/10?view=products&display=card&q=ThinkPad&sort=price&page=1");
  const rail = page.locator(".sp-side");
  await expect(rail.locator('[data-runtime-project="10"]')).toHaveClass("active");
  await rail.evaluate(node => { (node as HTMLElement).dataset.mountCheck = "persistent"; });
  const source = page.url();
  await rail.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "系统设置", exact: true })).toBeVisible();
  await expect(rail).toHaveAttribute("data-mount-check", "persistent");
  await expect(page.locator(".sp-side")).toHaveCount(1);
  await expect(page.getByRole("link", { name: "连接与设置", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "设置", exact: true })).toHaveCount(1);
  await expect(rail.getByRole("link", { name: "设置", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(rail.getByRole("navigation", { name: "当前项目", exact: true }).locator('[aria-current="page"]')).toHaveCount(0);
  await expect(rail.locator('[data-runtime-project="10"] .sp-status')).toHaveCount(2);
  await expect(page.locator(".ss-welcome")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "重新运行配置向导", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "系统配置", exact: true }).getByRole("button", { name: "闲鱼账户", exact: true }).click();
  await page.reload();
  await expect(rail.locator('[data-runtime-project="10"]')).toHaveClass("active");
  await page.getByRole("link", { name: "返回商品列表", exact: true }).click();
  expect(page.url()).toBe(source);
  await page.goBack();
  await expect(page.getByRole("heading", { name: "系统设置", exact: true })).toBeVisible();
  await rail.getByRole("navigation", { name: "当前项目", exact: true }).getByRole("button", { name: "监控任务", exact: true }).click();
  await expect(page).toHaveURL(/projects\/10\?view=monitors$/);
  await rail.getByRole("link", { name: "设置", exact: true }).click();
  await rail.getByRole("button", { name: "运行中心", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "工作空间运行概况", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/settings"); // Direct URL uses the last safe project context.
  await expect(rail.locator('[data-runtime-project="10"]')).toHaveClass("active");
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
  expect(writes).toEqual([]);
  await page.screenshot({ path: info.outputPath("shared-settings-navigation.png"), fullPage: true });
});

test("settings retains natural project list sizing and independent scrolling with 2, 10 and 20 projects", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "Narrow layout retains its existing project select.");
  for (const count of [2, 10, 20]) {
    await manyProjects(page, count);
    await page.setViewportSize({ width: 1440, height: 780 });
    await page.goto("/projects/1?view=research");
    const list = page.getByRole("region", { name: "选购项目列表", exact: true });
    while (await list.getByRole("button", { name: /显示更多项目/ }).count()) await list.getByRole("button", { name: /显示更多项目/ }).click();
    await list.evaluate(node => { node.scrollTop = 80; });
    const scroll = await list.evaluate(node => node.scrollTop);
    await page.locator(".sp-side").getByRole("link", { name: "设置", exact: true }).click();
    await expect(page.getByRole("heading", { name: "系统设置", exact: true })).toBeVisible();
    expect(await list.evaluate(node => node.scrollTop)).toBe(scroll);
    await expect(list.locator("[data-runtime-project]")).toHaveCount(count);
    if (count === 2) expect(await list.evaluate(node => node.scrollHeight-node.clientHeight)).toBeLessThanOrEqual(1);
    if (count > 2) {
      await list.hover(); await page.mouse.wheel(0, 200);
      await expect.poll(() => list.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
      await list.focus(); await page.keyboard.press("End");
      await expect(list.locator(`[data-runtime-project="${count}"]`)).toBeInViewport();
    }
    await page.setViewportSize({ width: 1440, height: 480 });
    const settings = page.locator(".sp-side").getByRole("link", { name: "设置", exact: true });
    await settings.focus(); await expect(settings).toBeInViewport();
    await expect(page.getByRole("button", { name: "新建选购项目", exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("unfinished setup is prominent inside settings, while completed setup keeps only the compact rerun", async ({ page }) => {
  await page.route("**/api/settings", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), setup_completed: false } });
  });
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "开始一段更聪明的选购研究", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "继续首次配置 →", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding\?/);
  await expect(page.getByRole("navigation", { name: "首次配置步骤", exact: true })).toBeVisible();
});
