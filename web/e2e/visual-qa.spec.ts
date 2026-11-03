import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

const screenshotDir = path.join(
  process.cwd(),
  "data",
  "diagnostics",
  "task-10",
  "screenshots",
);

async function assertNoPageOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    bodyClient: document.body.clientWidth,
    bodyScroll: document.body.scrollWidth,
    documentClient: document.documentElement.clientWidth,
    documentScroll: document.documentElement.scrollWidth,
  }));
  expect(dimensions.bodyScroll).toBeLessThanOrEqual(dimensions.bodyClient);
  expect(dimensions.documentScroll).toBeLessThanOrEqual(dimensions.documentClient);
}

async function assertOrderedRegions(regions: Locator[]) {
  const boxes = await Promise.all(regions.map((region) => region.boundingBox()));
  boxes.forEach((box) => expect(box).not.toBeNull());
  for (let index = 1; index < boxes.length; index += 1) {
    expect(boxes[index - 1]!.x + boxes[index - 1]!.width)
      .toBeLessThanOrEqual(boxes[index]!.x + 1);
  }
}

test("visual QA captures release viewports without overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "single-browser visual QA");

  for (const viewport of [
    { width: 1440, height: 900, name: "desktop-1440x900" },
    { width: 1024, height: 768, name: "tablet-1024x768" },
    { width: 390, height: 844, name: "mobile-390x844" },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/tasks/1");
    await expect(page.getByRole("heading", { name: "ThinkPad X1 Carbon 调研" }))
      .toBeVisible();
    await assertNoPageOverflow(page);

    const excerpt = page.locator(".candidate-excerpt");
    if (!(await excerpt.evaluate(element => (element as HTMLDetailsElement).open))) await excerpt.locator(":scope > summary").click();

    const cardButtons = page.locator(".candidate-excerpt .candidate-card__button");
    await expect(cardButtons).toHaveCount(4);
    const cardBoxes = await cardButtons.evaluateAll((cards) => cards.map((card) => {
      const box = card.getBoundingClientRect();
      return { height: box.height, width: box.width, x: box.x, y: box.y };
    }));
    expect(new Set(cardBoxes.map((box) => box.height)).size).toBe(1);
    expect(cardBoxes.every((box) => box.height >= 118 && box.width > 0)).toBe(true);
    if (viewport.width >= 768) {
      expect(cardBoxes[0].y).toBe(cardBoxes[1].y);
      expect(Math.abs(cardBoxes[0].width - cardBoxes[1].width)).toBeLessThan(1);
    } else {
      expect(cardBoxes[1].y).toBeGreaterThan(cardBoxes[0].y);
    }

    if (viewport.width >= 1180) {
      await assertOrderedRegions([
        page.getByRole("navigation", { name: "研究任务" }),
        page.getByRole("main"),
        page.getByRole("complementary", { name: "上下文检查器" }),
      ]);
      await cardButtons.first().click();
      const inspector = page.getByRole("complementary", { name: "上下文检查器" });
      await expect(inspector).toContainText("商品详细信息");
      await expect(inspector).toContainText("详情属性未独立验证");
    } else if (viewport.width >= 768) {
      await assertOrderedRegions([
        page.getByRole("navigation", { name: "研究任务" }),
        page.getByRole("main"),
      ]);
    } else {
      await expect(page.getByRole("button", { name: "查看任务" })).toBeVisible();
      await expect(page.getByRole("button", { name: "查看证据" })).toBeVisible();
    }

    await page.screenshot({
      path: path.join(screenshotDir, `${viewport.name}.png`),
    });

    if (viewport.width === 390) {
      await page.getByRole("button", { name: "查看任务" }).click();
      await expect(page.getByRole("dialog", { name: "研究任务" })).toBeVisible();
      await page.screenshot({
        path: path.join(screenshotDir, "mobile-390x844-task-drawer.png"),
      });
      await page.getByRole("button", { name: "关闭研究任务" }).click();
      // The conversation owns its collapsed state; reopen after returning from navigation.
      if (!(await excerpt.evaluate(element => (element as HTMLDetailsElement).open))) await excerpt.locator(":scope > summary").click();
      await cardButtons.first().click();
      const evidenceDrawer = page.getByRole("dialog", { name: "上下文检查器" });
      await expect(evidenceDrawer).toContainText("详情属性未独立验证");
      const drawerBox = await evidenceDrawer.boundingBox();
      expect(drawerBox).not.toBeNull();
      expect(drawerBox!.x).toBeGreaterThanOrEqual(0);
      expect(drawerBox!.x + drawerBox!.width).toBeLessThanOrEqual(viewport.width);
      await page.screenshot({
        path: path.join(screenshotDir, "mobile-390x844-evidence-drawer.png"),
      });
    }

    await page.goto("/tasks/1?tab=candidates");
    await expect(
      page.getByRole("searchbox", { name: "搜索标题或 listing ID" }),
    ).toBeVisible();
    await expect(page.getByRole("combobox", { name: "排序" })).toBeVisible();
    await assertNoPageOverflow(page);
    await page.screenshot({
      path: path.join(screenshotDir, `${viewport.name}-candidates.png`),
    });

    await page.goto("/tasks/1?tab=market");
    await expect(page.getByText("下四分位")).toBeVisible();
    await expect(page.getByRole("table", { name: "地区分布数据" })).toBeVisible();
    await expect(page.getByRole("table", { name: "每轮新增候选" })).toBeVisible();
    await assertNoPageOverflow(page);
    await page.screenshot({
      path: path.join(screenshotDir, `${viewport.name}-market.png`),
    });
  }
});

test("computed breakpoint styles match 767 768 1179 and 1180", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "single-browser breakpoint QA");

  for (const [width, expectedLayout, expectedColumns] of [
    [767, "mobile", 1],
    [768, "tablet", 2],
    [1179, "tablet", 2],
    [1180, "desktop", 2],
  ] as const) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/tasks/1");
    const shell = page.locator(".app-shell");
    await expect(shell).toHaveAttribute("data-layout", expectedLayout);
    const excerpt = page.locator(".candidate-excerpt");
    if (!(await excerpt.evaluate(element => (element as HTMLDetailsElement).open))) await excerpt.locator(":scope > summary").click();
    await expect(page.locator(".candidate-excerpt .candidate-card__button")).toHaveCount(4);
    await assertNoPageOverflow(page);

    const computed = await page.evaluate(() => {
      const toolbar = document.querySelector<HTMLElement>(".app-shell__toolbar");
      const grid = document.querySelector<HTMLElement>(".candidate-excerpt .candidate-grid");
      return {
        toolbarDisplay: toolbar ? getComputedStyle(toolbar).display : "missing",
        gridColumns: grid ? getComputedStyle(grid).gridTemplateColumns.split(" ").length : 0,
      };
    });
    expect(computed.gridColumns).toBe(expectedColumns);
    expect(computed.toolbarDisplay).toBe(width < 1180 ? "flex" : "missing");
    await expect(page.locator(".app-shell__context"))
      .toHaveCount(width >= 1180 ? 1 : 0);
  }
});
