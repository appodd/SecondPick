import { expect, test } from "@playwright/test";

// Let in-flight polling fixtures finish before Playwright closes their request context.
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: "wait" }); });

// Response and image fixtures are restricted to this isolated browser test.
test("saved first images render in both views and preview without closing the evidence drawer", async ({ page }, info) => {
  await page.route("**/test-media/*.svg", route => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100"><rect width="160" height="100" fill="#dbe6fb"/><text x="15" y="55">Saved product</text></svg>' }));
  await page.route("**/api/tasks/10/listings/*/images/*/content?*", route => route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100"><rect width="160" height="100" fill="blue"/></svg>'}));
  await page.route("**/api/tasks/10/listings/*/images", route => route.fulfill({ json: {
    listing_id: Number(route.request().url().split("/").at(-2)), images: [
      { id: 1, url: "/test-media/first.svg", display_url:new URL(route.request().url()).pathname+'/1/content?sha256='+ 'a'.repeat(64),state:'local_available',created_at: "2026-10-22" },
      { id: 2, url: "/test-media/second.svg", display_url:new URL(route.request().url()).pathname+'/2/content?sha256='+ 'b'.repeat(64),state:'local_available',created_at: "2026-10-22" },
    ] } }));
  await page.route("**/test-media/missing.jpg", route => route.fulfill({ status: 404, body: "missing" }));
  await page.route("**/api/projects/10/overview", async route => {
    const response = await route.fetch(); const data = await response.json();
    data.cards.sort((a: { listing_id: number }, b: { listing_id: number }) => b.listing_id - a.listing_id);
    data.cards[0].image_url = "/test-media/first.svg";
    data.cards[1].image_url = "/test-media/missing.jpg";
    await route.fulfill({ json: data });
  });
  await page.goto("/projects/10?view=products");
  const rowImage = page.locator(".sp-product-cell img").first();
  await expect(rowImage).toBeVisible();
  await expect.poll(() => rowImage.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBe(160);
  await expect(page.getByRole("img", { name: /图片加载失败/ }).first()).toBeVisible();
  await expect(page.getByRole("img", { name: /来源未提供图片/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "卡片", exact: true }).click();
  await expect(page.locator(".sp-card-image img").first()).toHaveAttribute("src", /first.svg/);
  await page.locator(".sp-card-image").first().click();
  const evidence = page.getByRole("dialog", { name: "商品与卖家证据" });
  await evidence.getByRole("button", { name: "放大商品首图" }).click();
  const viewer = page.getByRole("dialog", { name: "商品图片预览" });
  await expect(viewer).toBeVisible();
  await viewer.getByRole("button", { name: "放大图片", exact: true }).click();
  await expect(viewer.getByText("150%", { exact: true })).toBeVisible();
  await viewer.getByRole("button", { name: "下一张图片" }).click();
  await expect(viewer.getByRole("link", { name: "打开原图" })).toHaveAttribute("href", /\/2\/content\?sha256=b{64}$/);
  await page.keyboard.press("Escape");
  await expect(viewer).toBeHidden();
  await expect(evidence).toBeVisible();
  await page.screenshot({ path: info.outputPath("product-images.png"), fullPage: true });
});

test("new monitor page reads progress and round logs, persists selection and never controls collection", async ({ page }, info) => {
  const current = "a".repeat(32), older = "b".repeat(32);
  let reads = 0;
  const posts: string[] = [];
  page.on("request", request => { if (request.method() !== "GET") posts.push(request.url()); });
  const monitor = { id: 91, task_id: 10, state: "running", desired_state: null, keyword: "日志测试", max_pages: 3, max_items: 50,
    interval_seconds: 1800, max_rounds: 20, collect_seller_profiles: false, rounds: 2, imported: 11, next_run_at: null,
    error_code: null, updated_at: "2026-10-22T02:00:00Z", result: { worker_status: { phase: "collecting", error_code: null } } };
  await page.route("**/api/projects/10/monitors", route => route.fulfill({ json: { items: [{ monitor_id: 91, name: "已有监控", mode: "ongoing", duration_seconds: null, revision: 0, monitor, runs: [] }] } }));
  await page.route("**/monitors/91/events?*", route => route.fulfill({ json: { items: [{ id: 1, code: "round_started", phase: "process", created_at: monitor.updated_at, counts: {} }], has_more: false, next_before_id: null } }));
  await page.route("**/monitors/91/logs?*", route => {
    reads++;
    const params = new URL(route.request().url()).searchParams;
    const round = params.get("round_id") || current;
    route.fulfill({ json: { items: [{ at: monitor.updated_at, text: params.has("before") ? "earlier output" : round === older ? "older round output" : `live output ${reads}` }],
      rounds: [{ id: current, updated_at: monitor.updated_at }, { id: older, updated_at: "2026-10-21T02:00:00Z" }], round_id: round,
      next_before: params.has("before") ? null : 100, has_more: !params.has("before"), capture_enabled: true, max_bytes: 4194304, max_rounds: 5 } });
  });
  await page.goto("/projects/10?view=monitors");
  await expect(page.getByText("最近采集开始", { exact: false })).toBeVisible();
  expect(reads).toBe(0);
  await page.getByRole("button", { name: "查看采集日志", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "已有监控 · 采集日志" });
  await expect(drawer.getByRole("log")).toContainText("live output");
  await expect.poll(() => reads).toBeGreaterThan(1);
  await drawer.getByLabel("自动刷新日志").uncheck();
  await drawer.getByRole("combobox", { name: "日志采集轮次" }).selectOption(older);
  await expect(drawer.getByRole("log")).toContainText("older round output");
  await expect(page).toHaveURL(new RegExp(`logRound=${older}`));
  await page.reload();
  await expect(page.getByRole("log")).toContainText("older round output");
  await page.getByRole("button", { name: "查看更早日志" }).click();
  await expect(page.getByRole("log")).toContainText("earlier output");
  await page.getByRole("button", { name: "回到最新日志" }).click();
  await expect(page.getByRole("log")).toContainText("live output");
  expect(posts).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("project-monitor-logs.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "已有监控 · 采集日志" })).toBeHidden();
  await expect(page.getByRole("button", { name: "查看采集日志", exact: true })).toBeFocused();
});
