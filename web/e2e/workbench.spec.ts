import { expect, test } from "@playwright/test";

async function openTaskNavigation(page: import("@playwright/test").Page) {
  const trigger = page.getByRole("button", { name: "查看任务" });
  if ((page.viewportSize()?.width ?? 1440) < 768) {
    await expect(trigger).toBeVisible();
    await trigger.click();
  }
}

test("task switch updates the URL and task header", async ({ page }) => {
  // Force the destination onto a later page even when this test runs alone.
  const response = await page.request.get("/api/tasks?limit=100");
  expect(response.ok()).toBe(true);
  const taskPage = await response.json();
  const destination = taskPage.items.find((task: { id: number }) => task.id === 2);
  expect(destination).toBeTruthy();
  const firstPage = taskPage.items.filter((task: { id: number }) => task.id !== 2);
  await page.route("**/api/tasks?*", async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get("offset") ?? 0);
    const items = offset === 0 ? firstPage : [destination];
    await route.fulfill({ json: { items, total_count: firstPage.length + 1, returned_count: items.length,
      truncated: offset === 0, page: { offset, limit: firstPage.length, has_more: offset === 0,
        next_offset: offset === 0 ? firstPage.length : null } } });
  });
  await page.goto("/tasks/1");
  await openTaskNavigation(page);
  const navigation = page.getByLabel("任务列表");
  await expect(navigation.getByText(/显示 \d+ \/ \d+ 个任务/)).toBeVisible();
  const target = navigation.getByRole("link", { name: /Pocket 3 调研/ });
  for (let index = 0; index < 10 && await target.count() === 0; index++) {
    const loaded = await navigation.locator("li").count();
    await navigation.getByRole("button", { name: "加载更多任务", exact: true }).click();
    await expect.poll(() => navigation.locator("li").count()).toBeGreaterThan(loaded);
  }
  await target.click();

  await expect(page).toHaveURL(/\/tasks\/2/);
  await expect(page.getByRole("heading", { name: "Pocket 3 调研" })).toBeVisible();
});

test("all candidates separates loaded and total counts", async ({ page }) => {
  await page.goto("/tasks/1?tab=candidates");

  await expect(page.getByLabel("候选计数")).toContainText("已返回 50 条");
  await expect(page.getByLabel("候选计数")).toContainText("去重候选 55 条");

  await page.getByRole("combobox", { name: "证据状态" }).selectOption("captured");
  await expect(page.locator(".candidate-title-button")).toHaveCount(2);
  await page.getByRole("combobox", { name: "证据状态" }).selectOption("");
  await page.getByRole("combobox", { name: "排序" }).selectOption("price_desc");
  await expect(page.locator(".candidate-title-button").first())
    .toHaveText("ThinkPad X1 Carbon #50");
});

test("selecting a row updates the persistent desktop inspector", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "desktop-only inspector contract");
  await page.goto("/tasks/1?tab=candidates");

  await page.getByRole("button", { name: /ThinkPad X1 Carbon #01/ }).click();

  await expect(page).toHaveURL(/listing=1/);
  const inspector = page.getByRole("complementary", { name: "上下文检查器" });
  await expect(inspector).toContainText("ThinkPad X1 Carbon #01");
  await expect(inspector).toContainText("详情属性未独立验证");
});

test("two candidates open comparison without a score", async ({ page }) => {
  await page.goto("/tasks/1?tab=candidates");
  await page.getByRole("checkbox", { name: /ThinkPad X1 Carbon #01/ }).check();
  await page.getByRole("checkbox", { name: /ThinkPad X1 Carbon #02/ }).check();
  await page.getByRole("tab", { name: "对比" }).click();

  await expect(page.getByRole("table").first()).toContainText("ThinkPad X1 Carbon #01");
  await expect(page.getByRole("table").first()).toContainText("ThinkPad X1 Carbon #02");
  await expect(page.getByRole("row", { name: /市场中位价比例/ })).toBeVisible();
  await expect(page.getByRole("main")).not.toContainText(/推荐分|评分|score/i);
});

test("market overview exposes numeric table values", async ({ page }) => {
  await page.goto("/tasks/1?tab=market");

  const distribution = page.getByRole("table", { name: "价格分布数据" });
  await expect(distribution).toBeVisible();
  await expect(distribution.getByRole("cell", { name: "¥5,101" })).toBeVisible();
  await expect(distribution.getByRole("cell", { name: "1", exact: true }).first()).toBeVisible();
  await expect(page.getByText("目标地区覆盖 55 / 55（100.0%）")).toBeVisible();
  await expect(page.getByRole("table", { name: "每轮新增候选" })).toBeVisible();
  await expect(page.getByText("停止条件").locator("..")).toContainText("collecting");
});

test("research and debug views preserve task and selected listing", async ({ page }) => {
  await page.goto("/tasks/1?tab=candidates&listing=1");
  await page.getByRole("button", { name: "调试视图" }).click();

  await expect(page).toHaveURL(/\/tasks\/1\?.*listing=1.*view=debug|\/tasks\/1\?.*view=debug.*listing=1/);
  await expect(page.getByRole("heading", { name: "调试视图" })).toBeVisible();
  await page.getByRole("button", { name: "研究视图" }).click();
  await expect(page).toHaveURL(/listing=1/);
  await expect(page.getByText("ThinkPad X1 Carbon #01", { exact: false }).last()).toBeVisible();
});

test("mobile evidence opens in a drawer and closes without overlap", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "mobile-only drawer contract");
  await page.goto("/tasks/1?tab=candidates");
  await page.getByRole("button", { name: /ThinkPad X1 Carbon #01/ }).click();

  const drawer = page.getByRole("dialog", { name: "上下文检查器" });
  await expect(drawer).toBeVisible();
  const box = await drawer.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "关闭上下文检查器" }).click();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(/^(?!.*context=open).*$/);
});

test("settings separate Codex CLI authentication and runtime states", async ({ page }) => {
  await page.goto("/settings?section=codex");
  await expect(page.getByRole("heading", { name: "AI 研究驱动", exact: true })).toBeVisible();
  await expect(page.getByText("Codex CLI", { exact: true })).toBeVisible();
  await expect(page.getByText("版本与当前运行状态", { exact: true })).toBeVisible();
  await expect(page.locator(".ss-row").filter({ hasText: "版本与当前运行状态" }).getByText("未知", { exact: true })).toBeVisible();
});

test("task rail stays in view when the main workspace scrolls", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "persistent rail on desktop/tablet");
  for (const width of [1440, 1024]) {
    await page.setViewportSize({ width, height: 768 });
    await page.goto("/tasks/1?tab=candidates");
    await expect(page.locator(".candidate-title-button")).toHaveCount(50);
    const before = await page.getByRole("navigation", { name: "研究任务" }).boundingBox();
    await page.getByRole("main").evaluate(element => element.scrollTo(0, 900));
    await expect.poll(() => page.getByRole("main").evaluate(element => element.scrollTop)).toBeGreaterThan(300);
    const after = await page.getByRole("navigation", { name: "研究任务" }).boundingBox();
    expect(after!.y).toBe(before!.y);
    expect(after!.height).toBe(768);
    await expect(page.getByRole("link", { name: "设置", exact: true })).toBeVisible();
  }
});

test("desktop columns scroll independently and evidence heading stays visible", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "three persistent desktop columns");
  await page.setViewportSize({ width: 1440, height: 768 });
  await page.goto("/tasks/1?tab=candidates&listing=1");
  await expect(page.locator("#listing-evidence-title")).toBeVisible();
  // The inspector can finish before the task/main workspace data arrives.
  // A wheel event over the loading placeholder cannot scroll the candidate list.
  await expect(page.locator(".candidate-title-button")).toHaveCount(50);
  const main = page.getByRole("main");
  const inspector = page.locator(".app-shell__context");
  const rail = page.getByRole("navigation", { name: "研究任务" });
  const taskList = rail.locator(".task-groups");
  // Add ordinary local fixture rows to exercise a long task history.
  await expect(taskList.locator("ul li").first()).toBeVisible();
  await taskList.evaluate(element => {
    const list = element.querySelector("ul")!;
    const row = list.querySelector("li")!;
    for (let index = 0; index < 40; index++) list.append(row.cloneNode(true));
  });
  const leftBefore = await rail.boundingBox();
  const rightBefore = await inspector.boundingBox();
  await main.hover({ position: { x: 300, y: 500 } });
  await page.mouse.wheel(0, 600);
  await expect.poll(() => main.evaluate(element => element.scrollTop)).toBeGreaterThan(300);
  const mainPosition = await main.evaluate(element => element.scrollTop);
  expect(await inspector.evaluate(element => element.scrollTop)).toBe(0);
  expect(await taskList.evaluate(element => element.scrollTop)).toBe(0);
  expect(await rail.boundingBox()).toEqual(leftBefore);
  expect(await inspector.boundingBox()).toEqual(rightBefore);
  expect(await page.evaluate(() => scrollY)).toBe(0);
  await inspector.hover({ position: { x: 100, y: 400 } });
  await page.mouse.wheel(0, 700);
  await expect.poll(() => inspector.evaluate(element => element.scrollTop)).toBeGreaterThan(50);
  expect(await main.evaluate(element => element.scrollTop)).toBe(mainPosition);
  await expect(page.locator("#listing-evidence-title")).toBeVisible();
  await expect(page.getByRole("button", { name: "关闭商品证据" })).toBeVisible();
  const inspectorPosition = await inspector.evaluate(element => element.scrollTop);
  await taskList.hover();
  await page.mouse.wheel(0, 500);
  await expect.poll(() => taskList.evaluate(element => element.scrollTop)).toBeGreaterThan(100);
  expect(await main.evaluate(element => element.scrollTop)).toBe(mainPosition);
  expect(await inspector.evaluate(element => element.scrollTop)).toBe(inspectorPosition);
  await expect(rail.getByRole("link", { name: "设置", exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("independent-columns.png") });
  await page.getByRole("button", { name: "关闭商品证据" }).click();
  await expect(page).not.toHaveURL(/listing=/);
  await expect(page.locator("#task-overview-title")).toBeVisible();
  expect(await main.evaluate(element => element.scrollTop)).toBe(mainPosition);
  expect(await inspector.evaluate(element => element.scrollTop)).toBe(0);
});

test("mobile evidence drawer scrolls internally while its header and background stay fixed", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile-chromium", "mobile drawer scroll contract");
  await page.goto("/tasks/1?tab=candidates");
  const main = page.getByRole("main");
  await main.evaluate(element => element.scrollTo(0, 200));
  await page.getByRole("button", { name: /ThinkPad X1 Carbon #01/ }).click();
  const drawer = page.getByRole("dialog", { name: "上下文检查器" });
  await expect(drawer).toBeVisible();
  const content = drawer.locator(".responsive-drawer__content");
  // Opening the drawer precedes the asynchronous evidence response. Wheel over
  // a short loading placeholder is consumed before there is anything to scroll.
  await expect(drawer.getByRole("heading", { name: "ThinkPad X1 Carbon #01", exact: true })).toBeVisible();
  await expect.poll(() => content.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(50);
  await expect(drawer.getByRole("button", { name: "关闭商品证据" })).toBeHidden();
  const header = drawer.locator(".responsive-drawer__header");
  const headerBefore = await header.boundingBox();
  const mainBefore = await main.evaluate(element => element.scrollTop);
  await content.hover({ position: { x: 100, y: 350 } });
  await page.mouse.wheel(0, 800);
  await expect.poll(() => content.evaluate(element => element.scrollTop)).toBeGreaterThan(50);
  expect(await header.boundingBox()).toEqual(headerBefore);
  expect(await main.evaluate(element => element.scrollTop)).toBe(mainBefore);
  await expect(drawer.getByRole("button", { name: "关闭上下文检查器" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("drawer-independent-scroll.png") });
  await drawer.getByRole("button", { name: "关闭上下文检查器" }).click();
  expect(await main.evaluate(element => element.scrollTop)).toBe(mainBefore);
  await expect(drawer).toBeHidden();
});
