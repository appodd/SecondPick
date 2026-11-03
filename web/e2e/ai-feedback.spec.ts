import { expect, test, type Page } from "@playwright/test";

const result = { title: "MacBook 选购", goal: "AI 整理目标", budget: 6000, hard: ["16GB 内存", "M 系列芯片"], soft: ["优先原装"], minimum: 30, auto_research: true };
const releases = new WeakMap<Page, () => void>();
async function open(page: Page) {
  await page.goto("/projects/10");
  await page.getByRole("button", { name: "新建选购项目", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "新建选购项目", exact: true });
  await dialog.getByRole("textbox", { name: "选购目标", exact: true }).fill("买一台 MacBook，预算6000元，16GB内存");
  return dialog;
}
test.afterEach(async ({ page }) => { releases.get(page)?.(); await page.unrouteAll({ behavior: "wait" }); });

test("long parsing is visible, duplicate-safe, editable, reduced-motion aware and preserves manual fields", async ({ page }, info) => {
  let release!: () => void; const gate = new Promise<void>(done => { release = done; }); let calls = 0;
  releases.set(page, release);
  await page.route("**/api/project-goal-drafts", async route => { calls++; await gate; await route.fulfill({ json: result }); });
  await page.clock.install();
  const dialog = await open(page);
  await dialog.getByRole("button", { name: "AI 解析需求", exact: true }).dblclick();
  const feedback = dialog.getByLabel("AI 处理反馈");
  await expect(feedback).toContainText("AI 正在解析选购目标…");
  await expect(dialog.getByRole("button", { name: "AI 解析需求", exact: true })).toBeDisabled();
  await expect.poll(() => calls).toBe(1);
  expect(await feedback.evaluate(node => getComputedStyle(node, "::before").animationDuration)).toBe("8s");
  await dialog.getByLabel("预算上限（元）", { exact: true }).fill("4200");
  await dialog.getByRole("textbox", { name: "硬条件（每行一项）", exact: true }).fill("32GB 内存");
  await page.clock.runFor(16000);
  await expect(feedback).toContainText("仍在等待 AI 返回");
  await page.clock.runFor(30000);
  await expect(feedback).toContainText("本次等待较久");
  await page.screenshot({ path: info.outputPath("ai-waiting.png") });
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await feedback.evaluate(node => getComputedStyle(node, "::before").animationName)).toBe("none");
  expect(await feedback.locator("svg").evaluate(node => getComputedStyle(node).animationName)).toBe("none");
  release();
  await expect(feedback).toHaveAttribute("data-state", "success");
  await expect(dialog.getByLabel("项目名称", { exact: true })).toHaveValue("MacBook 选购");
  await expect(dialog.getByLabel("预算上限（元）", { exact: true })).toHaveValue("4200");
  await expect(dialog.getByRole("textbox", { name: "硬条件（每行一项）", exact: true })).toHaveValue("32GB 内存");
  await expect(dialog.getByRole("checkbox")).not.toBeChecked();
  await expect(dialog.getByLabel("已整理的选购条件")).toContainText("32GB 内存");
  await expect(dialog.getByRole("progressbar")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("ai-success.png") });
});

test("failed parsing retains inputs and exposes manual entry and a successful explicit retry", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/project-goal-drafts", route => route.fulfill(++calls === 1 ? { status: 503, json: { detail: "AI 暂不可用" } } : { json: result }));
  const dialog = await open(page);
  await dialog.getByLabel("项目名称", { exact: true }).fill("我的项目");
  await dialog.getByRole("button", { name: "AI 解析需求", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("需求解析未完成");
  await dialog.getByRole("button", { name: "手动填写", exact: true }).click();
  await expect(dialog.getByLabel("项目名称", { exact: true })).toBeFocused();
  await expect(dialog.getByLabel("项目名称", { exact: true })).toHaveValue("我的项目");
  await dialog.getByRole("button", { name: "重试解析", exact: true }).click();
  await expect(dialog.getByLabel("AI 处理反馈")).toHaveAttribute("data-state", "success");
  expect(calls).toBe(2);
});

test("changing the submitted goal prevents a late AI response from replacing the new form", async ({ page }) => {
  let release!: () => void; const gate = new Promise<void>(done => { release = done; });
  releases.set(page, release);
  await page.route("**/api/project-goal-drafts", async route => { await gate; await route.fulfill({ json: result }); });
  const dialog = await open(page);
  await dialog.getByRole("button", { name: "AI 解析需求", exact: true }).click();
  await dialog.getByRole("textbox", { name: "选购目标", exact: true }).fill("改为买一台相机");
  await dialog.getByLabel("项目名称", { exact: true }).fill("相机选购");
  release();
  await expect(dialog.getByLabel("AI 处理反馈")).toHaveAttribute("data-state", "notice");
  await expect(dialog.getByText("选购目标已修改，请重新解析", { exact: true })).toBeVisible();
  await expect(dialog.getByLabel("项目名称", { exact: true })).toHaveValue("相机选购");
  await expect(dialog.getByLabel("预算上限（元）", { exact: true })).toHaveValue("");
});
