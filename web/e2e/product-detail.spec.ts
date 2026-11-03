import { expect, test } from "@playwright/test";

// All response overrides below belong to the isolated offline fixture service.
test("drawer surfaces saved seller information and hides missing fields and technical records", async ({ page }, info) => {
  const writes: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/") && request.method() !== "GET") writes.push(request.url()); });
  await page.route("**/api/projects/10/listings/*/seller", route => route.fulfill({ json: { seller_id: "12345", profile: {
    卖家芝麻信用: "none", 卖家注册时长: "来闲鱼9年1个月", 作为卖家的好评率: "100.00%", "卖家在售/已售商品数": "23",
  }, result: null, fresh: false, observed_at: "2026-10-22T00:00:00Z", researched_at: null } }));
  await page.route("**/api/listings/*/evidence?*", async route => {
    const response = await route.fetch(); const data = await response.json();
    data.detail_status = "captured";
    data.detail = { snapshot_id: 18, run_id: 1, description: "卖家自述：自用闲置，键盘有使用痕迹。", attributes: { 内存: "16GB", 硬盘: "512GB", 空值: "null" }, attributes_source: "seller_entered_attribute", evidence_source: "seller_entered_attribute", independently_verified: false };
    Object.keys(data.seller_fields.field_sources).forEach(key => { data.seller_fields[key] = null; data.seller_fields.field_sources[key] = "none"; });
    data.seller_fields.data_source = "none";
    await route.fulfill({ json: data });
  });
  await page.goto("/projects/10?view=products"); await page.locator(".sp-product-cell").first().click();
  const drawer = page.getByRole("dialog", { name: "商品与卖家证据" });
  await expect(drawer.getByRole("heading", { name: "AI 选购判断", exact: true })).toBeVisible();
  await expect(drawer.getByText("卖家自述：自用闲置，键盘有使用痕迹。", { exact: true })).toBeVisible();
  const seller = drawer.getByRole("region", { name: "卖家研究", exact: true });
  await expect(seller.getByText("100.00%", { exact: true })).toBeVisible();
  await expect(seller.getByText("来闲鱼9年1个月", { exact: true })).toBeVisible();
  await expect(seller.getByText("平台信用展示", { exact: true })).toHaveCount(0);
  await expect(seller.getByText("尚无已完成的卖家研究结论。", { exact: true })).toBeVisible();
  await expect(drawer.getByText("null", { exact: true })).toHaveCount(0);
  await expect(drawer.getByText("未记录", { exact: true })).toHaveCount(0);
  const diagnostics = drawer.locator(".le-diagnostics");
  await expect(diagnostics).not.toHaveAttribute("open"); await expect(diagnostics.getByText("详情快照记录")).toBeHidden();
  await seller.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("seller-saved-evidence.png") });
  await diagnostics.locator("summary").first().click(); await expect(diagnostics.getByText("详情快照记录")).toBeVisible();
  expect(await drawer.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  await page.keyboard.press("Escape"); await expect(drawer).toHaveCount(0);
  expect(writes).toEqual([]);
});

test("AI summary distinguishes seller claims, missing evidence and report membership", async ({ page }, info) => {
  await page.route("**/api/projects/10/overview", async route => {
    const response = await route.fetch({ maxRetries: 2 }); const data = await response.json();
    data.cards.sort((a: { listing_id: number }, b: { listing_id: number }) => b.listing_id - a.listing_id);
    const id = data.cards[0].listing_id;
    data.cards[0].research_state = "evaluated";
    data.report = { id: 20, candidate_ids_json: JSON.stringify([id]), content: "批次报告，仅用于上下文", snapshot_at: "2026-10-22T00:00:00Z", created_at: "2026-10-22T00:01:00Z", limited: 1 };
    data.studies = [{ id: 18, kind: "initial", state: "completed", listing_ids: [id], snapshot_at: "2026-10-22T00:00:00Z", created_at: "2026-10-22T00:00:00Z", finished_at: "2026-10-22T00:01:00Z", error: null,
      result: { content: "批次报告", candidate_ids: [id], research: { criteria: [
        { criterion_id: "memory", description: "内存要求", priority: "hard", source_refs: ["task_goal"], source_message_ids: [] },
        { criterion_id: "repair", description: "维修情况", priority: "hard", source_refs: ["task_goal"], source_message_ids: [] }],
        assessments: [{ listing_id: id, conclusion: "conditional", summary: "配置描述可参考，维修情况待核对", judgments: [
          { criterion_id: "memory", status: "MET", source_type: "seller_claim", reason: "卖家称内存16GB，尚未实物核对", evidence_refs: ["candidate:1"] },
          { criterion_id: "repair", status: "UNKNOWN", source_type: "missing", reason: "缺少可核验的维修记录", evidence_refs: [] }],
        }] } } }];
    data.studies[0].goal_revision = data.goal_context.current_revision;
    data.report.goal_revision = data.goal_context.current_revision;
    data.goal_context.report_current = true; data.goal_context.calibration = "current";
    await route.fulfill({ json: data });
  });
  await page.goto("/projects/10?view=products"); await page.locator(".sp-product-cell").first().click();
  const drawer = page.getByRole("dialog", { name: "商品与卖家证据" }); const summary = drawer.locator(".le-ai");
  await expect(summary.getByText("有条件考虑", { exact: true })).toBeVisible();
  await expect(summary.getByText("符合（据当前证据） · 卖家自述 · 实物待核实", { exact: true })).toBeVisible();
  await expect(summary.getByText("未知，待核实 · 信息缺失", { exact: true })).toBeVisible();
  await expect(summary.getByText(/目标版本及商品证据是否适用需结合当前研究状态核对/)).toBeVisible();
  await expect(summary.getByText("批次报告，仅用于上下文", { exact: true })).toBeHidden();
  await summary.getByText("查看引用依据（1）", { exact: true }).click();
  await expect(summary.getByText(/尚未返回对应输入原文/)).toBeVisible();
  await summary.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath("ai-judgment-evidence.png") });
  expect(await drawer.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
});

test("unreadable seller data remains unknown while product evidence stays usable", async ({ page }) => {
  await page.route("**/api/projects/10/listings/*/seller", route => route.fulfill({ status: 503, json: { detail: "暂不可用" } }));
  await page.goto("/projects/10?view=products"); await page.locator(".sp-product-cell").first().click();
  const drawer = page.getByRole("dialog", { name: "商品与卖家证据" });
  await expect(drawer.getByRole("alert")).toContainText("不能据此判断研究是否完成", { timeout: 15000 });
  await expect(drawer.getByText("尚无已完成的卖家研究结论。", { exact: true })).toHaveCount(0);
  await expect(drawer.getByRole("link", { name: /打开原始商品链接/ })).toBeVisible();
});
