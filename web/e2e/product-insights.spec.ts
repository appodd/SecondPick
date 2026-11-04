import { expect, test, type Page } from "@playwright/test";

// Controlled snapshots in the isolated 8876 test app, never production writes or AI.
async function fixture(page: Page, controller = false) {
  const data = await (await page.request.get("/api/projects/10/overview")).json();
  const savedListingId = data.cards[0].listing_id;
  const make = (id: number, title: string, price: number | null, state: string) => ({ listing_id: id, title, price_value: price, price_text: price === null ? null : `¥${price}`, research_state: state, url: `https://www.goofish.com/item?id=${id}`, location: "广州", seller_name: "测试卖家", source_run_ids: [], detail_status: "not_captured", search_condition: null });
  data.project.title = controller ? "NS2 Pro手柄" : "MacBook Pro"; data.project.goal = `选购 ${data.project.title}`;
  data.policy.budget = controller ? 400 : 5000; data.policy.hard = controller ? ["必须原装"] : ["内存至少16GB"];
  data.cards = controller ? [make(1, "NS2 Pro 原装手柄", 300, "summarized"), make(2, "NS2 Pro 手柄", 500, "waiting"), make(3, "NS2 Pro 手柄", null, "needs_information")]
    : [make(1, "MacBook Pro M2 16GB 512GB", 4500, "evaluated"), make(2, "MacBook Pro M2 8GB 256GB", 4000, "waiting"), make(3, "MacBook Pro M2 16GB 512GB", 6000, "evaluated"), make(4, "MacBook Pro M2 512GB", 4000, "summarized"), make(5, "MacBook Pro M2 16GB 512GB", null, "needs_information")];
  data.total = data.cards.length;
  data.goal_context = { current_revision: 2, report_current: true, calibration: "current", legacy_unmerged: false, original_goal: data.project.goal, automatic_calibration_supported: true, updated_at: "2026-10-23" };
  data.report = { id: 1, goal_revision: 2, content: "有限批次报告", candidate_ids_json: "[1,4]", snapshot_at: "2026-10-23", created_at: "2026-10-23", limited: 1 };
  data.studies = [{ id: 1, goal_revision: 2, state: "completed", kind: "initial", listing_ids: [1,3,4], snapshot_at: "2026-10-23", created_at: "2026-10-23", result: { content: "有限研究", candidate_ids: [1,4], research: { criteria: [], assessments: controller ? [] : [{ listing_id: 1, conclusion: "consider", summary: "配置与价格可考虑，机况仍待核实", judgments: [] }, { listing_id: 3, conclusion: "not_met", summary: "挂牌价超过当前预算", judgments: [] }] } } }];
  await page.route("**/api/projects/10/overview", route => route.fulfill({ json: data }));
  const writes: string[] = [];
  page.on("request", request => { if (!["GET", "HEAD"].includes(request.method())) writes.push(request.url()); });
  return { data, writes, savedListingId };
}
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: "wait" }));

test("match and evidence stay separate across products, shortlist, overview, research and drawer", async ({ page }, info) => {
  const { data, writes, savedListingId } = await fixture(page);
  data.policy.paused = true;
  data.report.study_id = 1;
  // Keep the drawer's evidence lookup bound to a real listing in the isolated
  // project; synthetic IDs used by table-only cases do not own task 10 evidence.
  data.cards[0].listing_id = savedListingId;
  data.report.candidate_ids_json = JSON.stringify([savedListingId, 4]);
  data.studies[0].listing_ids = [savedListingId, 3, 4];
  data.studies[0].result.research = {
    criteria: [{ criterion_id: "model", description: "型号符合", priority: "hard", source_refs: ["task_goal"] }],
    assessments: [{ listing_id: savedListingId, conclusion: "conditional", summary: "型号初步符合，实物待核实，仍有条件保留", judgments: [{ criterion_id: "model", status: "MET", source_type: "seller_claim", reason: "卖家明确声明型号；没有实物核验，也未查看图片链接", evidence_refs: [`detail:${savedListingId}:saved`] }] }],
  };
  await page.goto("/projects/10?view=products");
  const row = page.locator("tbody tr").filter({ hasText: `商品 #${savedListingId}` });
  await expect(row).toContainText("初步符合");
  await expect(row).toContainText("有条件考虑");
  await page.goto(`/projects/10?view=shortlist&compare=${savedListingId}`);
  const choices = page.locator(".ux2-decision-card").first();
  await choices.getByText("完整判断与来源",{exact:true}).click();
  await choices.getByText("条件匹配与证据 · 卖家自述").click();
  await expect(choices.getByText(/符合（据当前证据） · 卖家自述 · 实物待核实/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("match-evidence-shortlist.png"), fullPage: true });
  await page.goto("/projects/10?view=overview");
  await page.locator(".sp-overview-candidate").first().getByText("逐项判断与价格依据",{exact:true}).click();
  await page.locator(".sp-overview-candidate").first().getByText("条件匹配与证据 · 卖家自述").click();
  await expect(page.getByText(/符合（据当前证据） · 卖家自述 · 实物待核实/)).toBeVisible();
  await page.goto("/projects/10?view=research");
  await page.getByText("任务详情与证据",{exact:true}).click();
  await page.getByText("研究结论与依据", { exact: true }).click();
  await page.getByText("条件匹配与证据 · 卖家自述").click();
  await expect(page.getByText(/符合（据当前证据） · 卖家自述 · 实物待核实/)).toBeVisible();
  await page.goto("/projects/10?view=products");
  await row.locator("button.sp-product-cell").click();
  const drawer = page.getByRole("dialog", { name: "商品与卖家证据" });
  await expect(drawer.getByText(/符合（据当前证据） · 卖家自述 · 实物待核实/)).toBeVisible();
  expect(writes).toEqual([]);
});

test("MacBook counts are exclusive, filters and views agree, and research coverage is not recommendation", async ({ page }, info) => {
  const { writes } = await fixture(page);
  await page.goto("/projects/10?view=products");
  const summary = page.getByRole("region", { name: "项目商品概况" });
  await expect(summary.getByRole("button", { name: "已收录 5", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "初步符合 1", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "明确不符合 2", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "待核实 2", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "AI 报告候选 2", exact: true })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "条件匹配", exact: true })).toBeVisible();
  await expect(page.locator("tbody tr").filter({ hasText: "商品 #3" })).toContainText("不建议");
  const batch = page.locator("tbody tr").filter({ hasText: "商品 #4" });
  await expect(batch).toContainText("尚无可展示的逐项判断"); await expect(batch).not.toContainText("可考虑");
  await summary.getByRole("button", { name: "明确不符合 2", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await expect(summary).toContainText("当前筛选 2 件");
  await expect(summary).toContainText("已收录 5");
  await page.getByRole("combobox", { name: "商品排序" }).selectOption("match");
  await page.getByRole("button", { name: "卡片", exact: true }).click();
  await expect(page.locator(".sp-products-grid > .sp-panel")).toHaveCount(2);
  await page.reload();
  await expect(page.getByRole("combobox", { name: "条件匹配筛选" })).toHaveValue("outside");
  await page.getByRole("button", { name: "表格", exact: true }).click();
  await page.getByText("字段显隐",{exact:true}).click();
  await page.getByRole("group",{name:"显示字段"}).getByRole("checkbox",{name:"条件匹配",exact:true}).click();
  await expect(page.getByRole("group",{name:"显示字段"}).getByRole("checkbox",{name:"条件匹配",exact:true})).not.toBeChecked();
  await expect(page.getByRole("columnheader", { name: "条件匹配", exact: true })).toHaveCount(0);
  await page.getByRole("group",{name:"显示字段"}).getByRole("checkbox",{name:"条件匹配",exact:true}).click();
  await expect(page.getByRole("group",{name:"显示字段"}).getByRole("checkbox",{name:"条件匹配",exact:true})).toBeChecked();
  await page.keyboard.press("Escape");
  await summary.getByRole("button", { name: "AI 报告候选 2", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await page.getByRole("combobox", { name: "AI 判断筛选" }).selectOption("not_met");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody tr")).toContainText("商品 #3");
  await page.screenshot({ path: info.outputPath("macbook-insights.png"), fullPage: true });
  expect(writes).toEqual([]);
});

test("NS2 originality is pending, not inferred from title, and stale reports cannot become current recommendations", async ({ page }, info) => {
  const { data, writes } = await fixture(page, true);
  await page.goto("/projects/10?view=products");
  const summary = page.getByRole("region", { name: "项目商品概况" });
  await expect(summary.getByRole("button", { name: "已收录 3", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "初步符合 0", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "明确不符合 1", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "待核实 2", exact: true })).toBeVisible();
  await expect(page.locator("tbody")).not.toContainText("内存");
  await expect(page.locator("tbody")).toContainText("原装性等硬条件待核实");
  await page.screenshot({ path: info.outputPath("controller-insights.png"), fullPage: true });
  data.goal_context.current_revision = 3; data.goal_context.report_current = false; data.policy.budget = 250;
  await page.reload();
  await summary.getByText("筛选与数据来源",{exact:true}).click();
  await expect(summary).toContainText("目标 v3");
  await expect(summary.getByRole("button", { name: "明确不符合 2", exact: true })).toBeVisible();
  await expect(summary.getByRole("button", { name: "AI 报告候选 —", exact: true })).toBeDisabled();
  await expect(page.locator("tbody")).not.toContainText("报告重点候选");
  await page.getByRole("combobox", { name: "条件匹配筛选" }).selectOption("meets");
  await expect(page.getByRole("heading", { name: "没有匹配的商品", exact: true })).toBeVisible();
  expect(writes).toEqual([]);
});
