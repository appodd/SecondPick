import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/settings?section=xianyu");
  await page.getByRole("button", { name: /打开.*登录窗口/ }).click();
  await expect(page.getByRole("button", { name: "我已登录，验证连接" })).toBeEnabled();
  await page.reload();
  await page.getByRole("button", { name: "我已登录，验证连接" }).click();
  await expect(page.locator(".ss-panel-title .ss-badge")).toHaveText("已验证");
}
async function prepare(page: Page, query: string) {
  await page.goto("/new");
  await page.getByRole("textbox", { name: "对话输入" }).fill("action 请补充商品搜索");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "搜索词" })).toHaveValue("iPhone 15 Pro");
  await expect(page.getByRole("button", { name: "执行采集", exact: true })).toBeDisabled();
  await page.getByRole("textbox", { name: "搜索词" }).fill(query);
  await page.getByRole("checkbox", { name: /我已核对范围/ }).check();
  await page.getByRole("button", { name: "执行采集", exact: true }).click();
}

async function expandFinishedRequest(page: Page, status: string) {
  const card = page.locator(".action-request").first();
  await expect(card.locator(":scope > summary")).toContainText(status);
  await expect(card).not.toHaveAttribute("open");
  await card.locator(":scope > summary").click();
}

test("explicit login and search persist candidates and support follow-up analysis", async ({ page }, info) => {
  await login(page);
  await prepare(page, "iPhone 15 Pro");
  await expandFinishedRequest(page, "已完成");
  await expect(page.getByText("已完成 · 已保存 1 条商品记录")).toBeVisible();
  const audit = page.locator(".collection-audit").first();
  await audit.locator(":scope > summary").click();
  await expect(audit).toContainText("本次执行结束");
  await page.reload();
  await expandFinishedRequest(page, "已完成");
  await page.locator(".collection-audit").first().locator(":scope > summary").click();
  await expect(page.locator(".collection-audit").first()).toContainText("本次执行结束");
  await expect(page.getByRole("textbox", { name: "搜索词" })).toHaveValue("iPhone 15 Pro");
  await expect(page.getByRole("textbox", { name: "搜索词" })).toBeDisabled();
  await expect(page.locator(".conversation-item--system summary").filter({ hasText: "本次已保存 1 条商品记录" })).toBeVisible();
  await expect(page.locator(".conversation-item--assistant")).toHaveCount(1);
  await expect(page.getByText("助手已分析采集结果，结论已保存到对话。")).toBeVisible();
  const taskId = page.url().match(/tasks\/(\d+)/)![1];
  const candidates = await page.request.get(`/api/tasks/${taskId}/candidates`);
  expect((await candidates.json()).candidates[0].title).toBe("采集样例 iPhone 15 Pro");
  await page.getByRole("textbox", { name: "对话输入" }).fill("分析刚采集的商品");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".conversation-item--assistant")).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("collection-completed.png"), fullPage: true });
});

test("collection restores after reload, cancels, and retries only after a fresh acknowledgement", async ({ page }, info) => {
  await login(page);
  await prepare(page, "block 相机");
  await expect(page.getByRole("button", { name: "停止采集" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeDisabled();
  await page.screenshot({ path: info.outputPath("collection-running.png"), fullPage: true });
  await page.getByRole("button", { name: "停止采集" }).click();
  await expandFinishedRequest(page, "已停止");
  await expect(page.getByRole("button", { name: "重试采集" })).toBeDisabled();
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  await page.getByRole("checkbox", { name: /我已核对范围/ }).check();
  await page.getByRole("button", { name: "重试采集" }).click();
  await expandFinishedRequest(page, "已完成");
  await expect(page.getByText("已完成 · 已保存 1 条商品记录")).toBeVisible();
});

test("cooldown is visible without silently retrying", async ({ page }) => {
  await login(page);
  await prepare(page, "cooldown 相机");
  await expandFinishedRequest(page, "未完成");
  await expect(page.getByText("搜索冷却中，还需等待 30 秒。")).toBeVisible();
  await expect(page.getByRole("button", { name: "重试采集" })).toBeDisabled();
  await page.reload();
  await expandFinishedRequest(page, "未完成");
  await expect(page.getByText("搜索冷却中，还需等待 30 秒。")).toBeVisible();
});

for (const action of ["resume", "stop"] as const) {
  test(`detail verification survives refresh and supports ${action}`, async ({ page }) => {
    await login(page);
    await prepare(page, "iPhone 15 Pro");
    await expect(page.locator(".conversation-item--assistant")).toHaveCount(1);
    await page.getByRole("textbox", { name: "对话输入" }).fill("verify-detail 请核实候选详情");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const card = page.locator(".action-request").last();
    await card.getByRole("button", { name: "确认", exact: true }).click();
    await card.getByRole("checkbox", { name: /我已核对范围/ }).check();
    await card.getByRole("button", { name: "执行采集", exact: true }).click();
    await expect(card.getByRole("button", { name: "我已完成验证，继续采集" })).toBeVisible();
    await page.reload();
    await expect(card.getByRole("button", { name: "我已完成验证，继续采集" })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeDisabled();
    if (action === "resume") {
      await card.getByRole("button", { name: "我已完成验证，继续采集" }).click();
      await expect(card.locator(":scope > summary")).toContainText("已完成");
    } else {
      await card.getByRole("button", { name: "停止采集" }).click();
      await expect(card.locator(":scope > summary")).toContainText("已停止");
    }
    await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("conversation keeps ended collection compact and the next request actionable", async ({ page }, info) => {
  await login(page);
  await prepare(page, "iPhone 15 Pro");
  const historyCard = page.locator(".action-request").first();
  await expect(historyCard.locator(":scope > summary")).toContainText("已完成");
  await expect(historyCard).not.toHaveAttribute("open");
  await expect(page.locator(".conversation-item--assistant")).toHaveCount(1);
  await expect(page.getByRole("textbox", { name: "对话输入" })).toBeEnabled();
  await page.getByRole("textbox", { name: "对话输入" }).fill("action 请核实下一批商品");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".action-request")).toHaveCount(2);
  await expect(historyCard).not.toHaveAttribute("open");
  await expect(page.locator('.action-request[data-request-state="pending"]')).toHaveAttribute("open");
  await expect(page.getByRole("button", { name: "确认", exact: true })).toBeVisible();
  await expect(page.locator(".conversation-system-record")).not.toHaveAttribute("open");
  await expect(page.locator(".candidate-excerpt")).not.toHaveAttribute("open");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("conversation-clean-history.png"), fullPage: true });
});
