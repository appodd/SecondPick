import { test, expect } from "@playwright/test";

test("project pages and evidence drawer stay usable at 375/768/1024/1440", async ({
  page,
}) => {
  for (const width of [1440, 1024, 768, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/projects/10?view=products");
    await expect(page.getByRole("table")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
    await page.locator(".sp-product-cell").first().click();
    await expect(
      page.getByRole("dialog", { name: "商品与卖家证据" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "卖家研究", exact: true }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("dialog", { name: "商品与卖家证据" }),
    ).toHaveCount(0);
  }
});

test("SecondPick uses persisted project state, scoped research, independent favorites, and responsive views", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Each viewport owns a different seeded project in the shared isolated DB.
  const taskId = testInfo.project.name.startsWith("mobile") ? 11 : 10;
  await page.goto(`/projects/${taskId}`);
  await expect(
    page.getByRole("heading", { name: "当前 AI 研究结论", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "研究基线尚未形成" }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "当前项目" }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "当前项目" })
    .getByRole("button", { name: "全部商品", exact: true })
    .click();
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("checkbox", { name: "全选当前页" }).check();
  await expect(
    page.getByRole("button", { name: "AI 分析选中商品" }),
  ).toBeDisabled(); // fixture has >20
  await page.getByRole("button", { name: "取消选择", exact: true }).click();
  await page.getByRole("checkbox", { name: /选择 / }).first().check();
  await page.getByRole("button", { name: "AI 分析选中商品" }).click();
  await page.getByRole("button", { name: "提交本次研究", exact: true }).click();
  await expect(page.getByText(/AgentRun #.*已受理/)).toBeVisible();
  await page.getByRole("link", { name: "查看本次研究 →", exact: true }).click();
  await page
    .getByRole("navigation", { name: "当前项目" })
    .getByRole("button", { name: "Agent 研究", exact: true })
    .click();
  await expect(page.getByText(/AgentRun #.*指定范围/)).toBeVisible();
  await expect(page.getByText("研究结论与依据")).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "研究下一个有限批次" }).click();
  await expect(page.getByText(/AgentRun #.*首轮/)).toBeVisible();
  await expect(page.getByText("研究结论与依据")).toHaveCount(2, {
    timeout: 15000,
  });
  await page
    .getByRole("navigation", { name: "当前项目" })
    .getByRole("button", { name: "研究概览", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "当前研究判断" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("secondpick-overview.png"),
    fullPage: true,
  });
  await page
    .getByRole("navigation", { name: "当前项目" })
    .getByRole("button", { name: "候选清单", exact: true })
    .click();
  await page.getByRole("button", { name: "收藏", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "我的收藏" })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "取消收藏" }).first(),
  ).toBeVisible();
  await page.getByRole("checkbox", { name: /对比 / }).first().click();
  await expect(page.getByRole("checkbox", { name: /对比 / }).first()).toBeChecked();
  await expect(page.getByRole("heading", { name: /候选比较/ })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow).toBe(false);
  await page.goto("/");
  await page
    .getByRole("button", { name: "新建选购项目", exact: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "新建选购项目" });
  await dialog.getByLabel("选购目标").fill("测试隔离项目，不运行采集");
  await dialog
    .getByLabel("项目名称")
    .fill(`SecondPick-${testInfo.project.name}`);
  await dialog.getByRole("button", { name: "仅创建项目" }).click();
  await expect(
    page.getByRole("heading", {
      name: `SecondPick-${testInfo.project.name}`,
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("0 件去重商品")).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前研究判断" })).toHaveCount(
    0,
  );
  await page.reload();
  await expect(page.getByText("0 件去重商品")).toBeVisible();
  await page.getByRole("button", { name: "新建监控", exact: true }).click();
  const monitor = page.getByRole("dialog", { name: "监控计划草案" });
  await monitor.getByLabel("监控名称").fill("只审查，不启动");
  await monitor.getByLabel("搜索关键词").fill("索尼 A7");
  await monitor.getByRole("button", { name: "预览计划" }).click();
  await expect(monitor.getByText("待确认 · 尚未执行")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "研究基线尚未形成", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "当前项目" }).getByRole("button", { name: "监控任务", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "还没有监控任务" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("secondpick-empty.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
