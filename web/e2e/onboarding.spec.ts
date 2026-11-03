import { expect, test } from "@playwright/test";
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "wait" }));

test("settings reads actual local status without starting platform or AI actions", async ({ page }, info) => {
  const posts: string[] = [];
  page.on("request", request => { if (request.method() === "POST") posts.push(new URL(request.url()).pathname); });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "系统设置", exact: true })).toBeVisible();
  await expect(page.getByText("后端已连接", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "AI 研究驱动", exact: true }).click();
  await expect(page.getByText("版本与当前运行状态", { exact: true })).toBeVisible();
  await expect(page.locator(".ss-row").filter({ hasText: "版本与当前运行状态" }).getByText("未知", { exact: true })).toBeVisible();
  await expect(page.getByText("按需启动，当前未运行", { exact: true })).toHaveCount(0);
  expect(posts).toEqual([]);
  await page.screenshot({ path: info.outputPath("codex-settings.png"), fullPage: true });
});

test("first run resumes across dismiss and reload while history stays reachable", async ({ page }) => {
  await page.route("**/api/tasks?*", route => route.fulfill({ json: { items: [], total_count: 0 } }));
  await page.route("**/api/settings", async route => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), setup_completed: false } });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/onboarding\?/);
  await page.getByRole("button", { name: "3 AI 驱动" }).click();
  await expect(page.getByRole("heading", { name: "检查 AI 研究驱动" })).toBeVisible();
  await page.getByRole("button", { name: "暂时关闭" }).click();
  await expect(page.getByRole("heading", { name: "把寻找，交给研究。" })).toBeVisible();
  await page.reload();
  await expect(page).not.toHaveURL(/onboarding/);
  await page.getByRole("link", { name: /首次配置尚未完成/ }).click();
  await expect(page.getByRole("heading", { name: "检查 AI 研究驱动" })).toBeVisible();
});

test("wizard saves only completion and opens the existing project creator", async ({ page }) => {
  await page.route("**/api/tasks?*", route => route.fulfill({ json: { items: [], total_count: 0 } }));
  let patch: unknown;
  page.on("request", request => { if (request.method() === "PATCH" && request.url().endsWith("/api/settings")) patch = request.postDataJSON(); });
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "4 就绪检查" }).click();
  await page.getByRole("button", { name: "记录配置并继续" }).click();
  await expect(page.getByText("配置流程已记录", { exact: true })).toBeVisible();
  expect(patch).toEqual({ setup_completed: true });
  await page.reload();
  await expect(page.getByRole("link", { name: "创建第一个选购项目" })).toBeVisible();
  await page.getByRole("link", { name: "创建第一个选购项目" }).click();
  await expect(page.getByRole("dialog", { name: "新建选购项目" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "选购目标", exact: true })).toBeVisible();
});

test("settings review starts at step one and returns to its exact source on close or finish", async ({ page }, info) => {
  const source = "/settings?section=codex&returnTo=%2Fprojects%2F1%3Fview%3Dproducts%26display%3Dcard%26q%3DMacBook";
  await page.addInitScript(() => localStorage.setItem("secondpick-onboarding-step-v1", "4"));
  let patches = 0;
  await page.route("**/api/settings", async route => {
    if (route.request().method() === "PATCH") patches++;
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), setup_completed: true } });
  });
  await page.goto(source);
  await page.getByRole("link", { name: "重新运行配置向导" }).click();
  await expect(page.getByRole("heading", { name: "确认运行环境" })).toBeVisible();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await expect(page.getByRole("heading", { name: "连接闲鱼账户" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "连接闲鱼账户" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "确认运行环境" })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole("heading", { name: "连接闲鱼账户" })).toBeVisible();
  await page.getByRole("button", { name: "暂时关闭" }).click();
  await expect(page).toHaveURL(source);
  expect(patches).toBe(0);
  await page.getByRole("link", { name: "重新运行配置向导" }).click();
  await expect(page.getByRole("heading", { name: "确认运行环境" })).toBeVisible();
  await page.getByRole("button", { name: "4 就绪检查" }).click();
  await page.getByRole("button", { name: "记录配置并继续" }).click();
  await expect(page.getByRole("heading", { name: "返回你的工作空间" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("review-complete.png"), fullPage: true });
  await page.getByRole("button", { name: "完成并返回系统设置" }).click();
  await expect(page).toHaveURL(source);
  expect(patches).toBe(1);
});

test("direct wizard links cannot return outside the workspace and existing projects are not first users", async ({ page }) => {
  await page.route("**/api/settings", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), setup_completed: false } });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "继续你的选购研究", exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/onboarding/);
  await page.goto("/onboarding?returnTo=https%3A%2F%2Fexample.com&step=2");
  await page.getByRole("button", { name: "暂时关闭" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: "继续你的选购研究", exact: true })).toBeVisible();
});

test("initial completion returns to the workspace without creating or collecting anything", async ({ page }) => {
  await page.route("**/api/tasks?*", route => route.fulfill({ json: { items: [], total_count: 0 } }));
  let completed = false;
  await page.route("**/api/settings", async route => {
    const response = await route.fetch(); const data = await response.json();
    if (route.request().method() === "PATCH") completed = true;
    await route.fulfill({ json: { ...data, setup_completed: completed } });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "确认运行环境" })).toBeVisible();
  await page.getByRole("button", { name: "4 就绪检查" }).click();
  await page.getByRole("button", { name: "记录配置并继续" }).click();
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page).toHaveURL("/");
  await page.reload();
  await expect(page.getByRole("heading", { name: "把寻找，交给研究。" })).toBeVisible();
});

test("an unfinished configuration opened from a project restores its view and filters", async ({ page }) => {
  await page.route("**/api/settings", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), setup_completed: false } });
  });
  const source = "/projects/10?view=products&display=card&q=ThinkPad&sort=price&page=1";
  await page.goto(source);
  await page.getByRole("link", { name: /首次配置/ }).click();
  await page.getByRole("button", { name: "3 AI 驱动" }).click();
  await page.reload();
  await page.getByRole("button", { name: "暂时关闭" }).click();
  await expect(page).toHaveURL(source);
  await expect(page.locator('[data-runtime-project="10"]')).toHaveClass("active");
});

test("a failed browser status request stays unknown and cannot open login", async ({ page }) => {
  await page.route("**/api/browser/status", route => route.fulfill({ status: 503, json: { error: { code: "unavailable", message: "连接状态服务暂不可用" } } }));
  await page.goto("/settings?section=xianyu");
  await expect(page.getByRole("alert")).toContainText("闲鱼状态暂不可用");
  await expect(page.getByRole("button", { name: "打开闲鱼登录窗口" })).toBeDisabled();
  await expect(page.locator(".ss-panel-title .ss-badge")).toHaveText("状态未知");
});

test("failed completion is not acknowledged as saved", async ({ page }) => {
  await page.route("**/api/settings", async route => {
    if (route.request().method() === "PATCH") return route.fulfill({ status: 503, json: { error: { code: "write_failed", message: "无法保存配置记录" } } });
    return route.continue();
  });
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "4 就绪检查" }).click();
  await page.getByRole("button", { name: "记录配置并继续" }).click();
  await expect(page.getByRole("alert")).toContainText("无法保存配置记录");
  await expect(page.getByRole("heading", { name: "确认当前可用能力" })).toBeVisible();
});

test("diagnostics runs only the explicitly requested existing check", async ({ page }) => {
  const actions: string[] = [];
  page.on("request", request => { if (request.method() === "POST") actions.push(new URL(request.url()).pathname); });
  await page.goto("/settings?section=diagnostics");
  await page.getByRole("button", { name: "检查本地环境", exact: true }).click();
  await expect.poll(() => actions.length).toBe(1);
  await expect(page.getByRole("button", { name: "检查本地环境", exact: true })).toBeEnabled({ timeout: 30000 });
  expect(actions).toEqual(["/api/setup/check-environment"]);
  await page.getByRole("button", { name: "检查本地采集环境", exact: true }).click();
  await expect.poll(() => actions.length).toBe(2);
  await expect(page.getByRole("button", { name: "检查本地采集环境", exact: true })).toBeEnabled({ timeout: 30000 });
  expect(actions).toEqual(["/api/setup/check-environment", "/api/monitor-engine/check"]);
});

test("an explicitly opened login job can be restored and cancelled", async ({ page }) => {
  await page.goto("/settings?section=xianyu");
  await page.getByRole("button", { name: /打开.*登录窗口/ }).click();
  await expect(page.getByRole("button", { name: "我已登录，验证连接" })).toBeEnabled();
  await page.reload();
  await page.getByRole("button", { name: "取消登录任务" }).click();
  await expect(page.locator(".ss-notice").filter({ hasText: "登录任务 #" })).toContainText("cancelled");
  await expect(page.getByRole("button", { name: /打开.*登录窗口/ })).toBeEnabled();
});

test("expired login and unavailable AI have separate impact and recovery", async ({ page }) => {
  await page.route("**/api/browser/status", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), auth_status: "invalid" } });
  });
  await page.route("**/api/setup/status", async route => {
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({ json: { ...data, codex: { ...data.codex, cli_available: true, auth_available: false, detail: "authentication required" } } });
  });
  await page.route("**/api/setup/check-codex", route => route.fulfill({ status: 503, json: { error: { code: "probe_failed", message: "驱动检测暂不可用" } } }));
  await page.goto("/settings");
  await expect(page.getByText("需要重新登录", { exact: true })).toBeVisible();
  await expect(page.getByText("授权未通过", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "AI 研究驱动", exact: true }).click();
  await page.getByRole("button", { name: "检测 CLI 与授权" }).click();
  await expect(page.getByRole("alert")).toContainText("驱动检测暂不可用");
  await expect(page.locator(".ss-panel-title .ss-badge")).toHaveText("授权未通过");
});

test("settings and wizard fit desktop, tablet and narrow screens", async ({ page }, info) => {
  for (const width of [1440, 1024, 768, 375]) {
    await page.setViewportSize({ width, height: 900 });
    for (const url of ["/settings", "/settings?section=xianyu", "/onboarding"]) {
      await page.goto(url);
      if (url === "/onboarding") await page.getByRole("button", { name: "1 运行环境" }).click();
      await expect(page.getByRole("main")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    }
  }
  await page.screenshot({ path: info.outputPath("onboarding-narrow.png"), fullPage: true });
});
