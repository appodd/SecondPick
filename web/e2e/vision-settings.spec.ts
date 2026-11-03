import { expect, test } from "@playwright/test";

test("vision settings in the existing shell are offline, private and responsive", async ({ page }, info) => {
  let enabled = false, hasKey = false, checked = false;
  const mutations: string[] = [];
  const status = () => ({ settings: { enabled, provider: "deepseek", model: "deepseek-flash", timeout_seconds: 300, max_output_tokens: 3000 },
    state: !enabled ? "disabled" : !hasKey ? "not_configured" : checked ? "local_checked" : "saved_unverified",
    key_configured: hasKey, storage: "windows_dpapi", capability_declared: true, connection_verified: false,
    endpoint: "https://api.deepseek.com/responses", providers: [{ id: "deepseek", models: ["deepseek-flash"] }],
    local_check: checked ? { passed: hasKey, network_used: false } : null });
  await page.route("**/*", route => {
    const req = route.request(), u = new URL(req.url());
    if (!["127.0.0.1", "localhost"].includes(u.hostname)) return route.abort();
    if (!u.pathname.startsWith("/api/")) return route.continue();
    if (req.method() !== "GET") mutations.push(u.pathname);
    if (u.pathname.startsWith("/api/vision/")) {
      if (u.pathname.endsWith("/key/deepseek")) hasKey = req.method() === "PUT";
      if (u.pathname.endsWith("/settings") && req.method() === "PUT") enabled = req.postDataJSON().enabled;
      if (u.pathname.endsWith("/check")) checked = true;
      return route.fulfill({ json: status() });
    }
    if (u.pathname === "/api/settings") return route.fulfill({ json: { setup_completed: true, default_city: null, platforms: ["xianyu"], allow_ocr: true, preferred_view: "research" } });
    if (u.pathname === "/api/setup/status") return route.fulfill({ json: { setup_completed: true, environment: [], codex: { cli_available: false, auth_available: false, process_running: false, detail: "Offline fixture" }, xianyu: { profile_present: false, auth_status: "unknown" }, can_browse_existing_data: true, can_start_research: false } });
    if (u.pathname === "/api/health") return route.fulfill({ json: { status: "ok" } });
    if (u.pathname.startsWith("/api/tasks")) return route.fulfill({ json: { items: [], total_count: 0, returned_count: 0, truncated: false, page: { offset: 0, limit: 100, has_more: false, next_offset: null } } });
    return route.fulfill({ json: { auth_status: "unknown", enabled: false, max_pages: 3, active_job: null, login_job: null, result: null } });
  });
  await page.goto("/settings?section=vision");
  const panel = page.locator(".vision-settings");
  await expect(panel.getByRole("heading", { name: "视觉模型", exact: true })).toBeVisible();
  await expect(panel.getByText("功能已禁用", { exact: true })).toBeVisible();
  expect(mutations).toEqual([]);
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: "保存视觉配置" }).click();
  await panel.getByLabel("输入新 API Key").fill("SYNTHETIC-NOT-A-REAL-KEY");
  await panel.getByRole("button", { name: "保存或更新密钥" }).click();
  await expect(panel.getByLabel("输入新 API Key")).toHaveValue("");
  await panel.getByRole("button", { name: "检查配置（不联网）" }).click();
  await expect(panel.getByRole("status")).toHaveText("本地配置检查通过");
  await expect(panel.getByText(/真实连接：尚未验证/)).toBeVisible();
  expect(await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))).not.toContain("SYNTHETIC-NOT-A-REAL-KEY");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => scrollTo(0,0));
  await page.screenshot({ path: `../data/artifacts/p4b3-offline-20261025/vision-${info.project.name}.png`, fullPage: true });
  await panel.getByRole("button", { name: "清除密钥" }).click();
  await expect(panel.getByText(/尚未配置密钥/)).toBeVisible();
  expect(mutations.every(p => p.startsWith("/api/vision/"))).toBe(true);
});
