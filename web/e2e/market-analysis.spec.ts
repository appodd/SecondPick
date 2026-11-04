import { expect, test, type Page } from "@playwright/test";

// Fixture records live only in this isolated test. No real collection or AI calls.
async function fixture(page: Page, mode: "normal" | "unknown" | "empty" | "camera" | "many" = "normal") {
  // Immutable test inputs: do not leave route.fetch pending across legacy/settings navigation.
  const overviewTemplate = await (await page.request.get("/api/projects/10/overview")).json();
  const taskTemplate = await (await page.request.get("/api/tasks/10")).json();
  const make = (listing_id: number, title: string, price_value: number | null) => ({ listing_id, title, price_value, price_text: price_value === null ? null : `¥${price_value}`, url: `https://www.goofish.com/item?id=${listing_id}`, image_url: null,
    source_run_ids: [1], seller_name: "测试卖家", location: "上海", detail_status: "not_captured", search_condition: null, research_state: listing_id % 2 ? "evaluated" : "waiting", updated_at: "2026-10-22T02:00:00Z" });
  const title = "MacBook Pro M2 16GB 512GB 14寸 2023";
  const cards = mode === "many" ? Array.from({ length: 85 }, (_, index) => ({ ...make(101 + index, title, 4000 + index * 10), research_state: "evaluated" })) : mode === "normal" ? [make(101, title, 5666), ...[4000, 4500, 5000, 5000, 5500, 6000, 6500, 7000, 8000].map((price, index) => make(102 + index, title, price)),
    make(111, "MacBook Pro Intel i7 16GB 512GB 14寸 2023", 1000), make(112, "MacBook Pro Intel i7 16GB 512GB 14寸 2023", 1500),
    make(113, "MacBook Pro M3 16GB 512GB 14寸 2023", 12000), make(114, "MacBook Pro M2 32GB 1TB 14寸 2023", 9000), make(115, "MacBook Pro M2 16GB 1TB 14寸 2023", 6000),
    make(116, "MacBook Pro M2 8GB 16GB 256GB 512GB 多种配置", 2000), make(117, "MacBook Pro M2 16GB 512GB", null)]
    : mode === "unknown" ? [make(101, "MacBook Pro 16GB 512GB", 3000), make(102, "MacBook Pro 16GB 512GB", 3500), make(103, "MacBook Pro Intel i7 16GB 512GB", 2500), make(104, title, 5500)] : mode === "camera" ? [make(101, "索尼 A7III 单机 2020", 3000), make(102, "索尼 A7III 单机 2020", 3500)] : [make(101, title, null)];
  await page.route("**/api/projects/10/overview", async route => {
    const data = structuredClone(overviewTemplate);
    data.goal_context={current_revision:1,report_current:true,calibration:'current',legacy_unmerged:false}; delete data.market; data.cards = cards; data.total = cards.length; data.project.goal = "选购 MacBook Pro M2，16GB 内存、512GB 存储";
    data.report = { goal_revision:1, id: 1, study_id: 1, candidate_ids_json: "[101]", content: "有限样本研究", snapshot_at: "2026-10-21T02:00:00Z", created_at: "2026-10-21T03:00:00Z", limited: 1 };
    data.favorites = [101]; data.studies = []; data.policy.auto_research = 0; data.coverage.under_ai = 0;
    await route.fulfill({ json: data });
  });
  await page.route("**/api/listings/*/evidence?*", route => route.fulfill({ json: { ...cards[0], has_detail: false, search_description: null, search_description_status: "missing", detail: null,
    seller_fields: { field_sources: {}, independently_verified: false, data_source: "none" }, seller_other_items: [], evidence_conflicts: [], collection_state: { detail_snapshot_count: 0, valid_detail_snapshot_count: 0, blocked_detail_snapshot_count: 0, listing_lifetime_product_image_count: 0, listing_lifetime_downloaded_product_image_count: 0, listing_lifetime_ocr_result_count: 0 }, raw_text_excerpt: null } }));
  await page.route("**/api/tasks/10/listings/*/images", route => route.fulfill({ json: { listing_id: Number(new URL(route.request().url()).pathname.split("/").at(-2)), images: [] } }));
  await page.route("**/api/tasks/10", async route => {
    const data = structuredClone(taskTemplate);
    data.task.goal = data.task.original_goal = data.task.effective_goal = "选购 MacBook Pro M2，16GB 内存、512GB 存储";
    data.preference_revision_id = 0; data.preference_revisions = [];
    await route.fulfill({ json: data });
  });
  const writes: string[] = []; page.on("request", request => { if (request.method() !== "GET") writes.push(request.url()); });
  return { writes };
}
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: "wait" }); });

test("candidate analysis uses comparable peers, grouped prices, real quartiles and a marker", async ({ page }, info) => {
  const data = await fixture(page);
  await page.goto("/projects/10?view=shortlist");
  await page.locator(".ux2-decision-card details").first().locator("summary").click();
  await page.getByRole("link", { name: /查看行情参考/ }).first().click();
  await expect(page).toHaveURL(/display=market&marketFor=101/);
  await expect(page.getByLabel("行情处理器 / 芯片", { exact: true })).toHaveValue("M2");
  await expect(page.getByLabel("行情运行内存", { exact: true })).toHaveValue("16GB");
  const stats = page.getByLabel("挂牌价核心统计");
  await expect(stats).toContainText("9可用挂牌样本");
  await expect(stats).toContainText("¥5,500挂牌价中位数");
  await expect(stats).toContainText("¥5,000 – ¥6,500");
  await expect(page.getByLabel("候选挂牌价位置")).toContainText("位于本组样本中间 50%");
  await expect(page.locator(".sp-market-marker line")).toHaveCount(1);
  expect(await page.locator(".sp-market-bin").count()).toBeLessThanOrEqual(10);
  const before = await page.locator(".sp-market-bin").evaluateAll(nodes => nodes.map(node => node.getAttribute("aria-label")?.split("：")[0]));
  await page.getByLabel("行情存储容量", { exact: true }).selectOption("__all");
  await expect(stats).toContainText("10可用挂牌样本");
  await expect(page.getByText(/已放宽：存储容量/)).toBeVisible();
  const after = await page.locator(".sp-market-bin").evaluateAll(nodes => nodes.map(node => node.getAttribute("aria-label")?.split("：")[0]));
  expect(after).toEqual(before);
  await page.getByLabel("研究状态筛选", { exact: true }).selectOption("evaluated");
  await expect(stats).toContainText("5可用挂牌样本");
  await page.reload();
  await expect(page.getByLabel("行情存储容量", { exact: true })).toHaveValue("__all");
  await expect(page.getByLabel("研究状态筛选", { exact: true })).toHaveValue("evaluated");
  await expect(page.getByLabel("挂牌价核心统计")).toContainText("5可用挂牌样本");
  expect(data.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("market-candidate.png"), fullPage: true });
});

test("bin selection exposes actual samples and search/chart/table share filters", async ({ page }) => {
  await fixture(page);
  await page.goto("/projects/10?view=products&display=market&marketFor=101");
  await expect(page.locator(".sp-market-bin")).not.toHaveCount(0);
  await page.locator(".sp-market-bin").filter({ has: page.locator(".sp-market-bar-count") }).first().click();
  await expect(page.getByRole("button", { name: "显示全部比较样本", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "显示全部比较样本", exact: true }).click();
  await expect(page.getByRole("heading", { name: "比较样本 · 9 件", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "搜索商品", exact: true }).fill("找不到的文本");
  await expect(page.getByLabel("挂牌价核心统计")).toContainText("0可用挂牌样本");
  await expect(page.getByText(/当前范围没有可用于统计的挂牌样本/)).toBeVisible();
  await page.getByRole("button", { name: "表格", exact: true }).click();
  await expect(page.getByRole("heading", { name: "没有匹配的商品" })).toBeVisible();
});

test("unknown chip and limited samples are not silently mixed or classified as cheap", async ({ page }) => {
  await fixture(page, "unknown");
  await page.goto("/projects/10?view=products&display=market&marketFor=101");
  await expect(page.getByLabel("行情处理器 / 芯片", { exact: true })).toHaveValue("__unknown");
  await expect(page.getByLabel("挂牌价核心统计")).toContainText("1可用挂牌样本");
  await expect(page.getByLabel("候选挂牌价位置")).toContainText("暂不判定偏低或偏高");
  await page.getByLabel("行情处理器 / 芯片", { exact: true }).selectOption("__all");
  await expect(page.getByLabel("挂牌价核心统计")).toContainText("3可用挂牌样本");
  await expect(page.getByText(/已放宽：处理器/)).toBeVisible();
});

test("invalid prices and empty peer pools have no fabricated histogram or candidate position", async ({ page }) => {
  await fixture(page, "empty");
  await page.goto("/projects/10?view=products&display=market&marketFor=101");
  await expect(page.getByLabel("挂牌价核心统计")).toContainText("0可用挂牌样本");
  await expect(page.locator(".sp-market-bin")).toHaveCount(0);
  await expect(page.getByLabel("候选挂牌价位置")).toContainText("报价或配置不明确");
  await expect(page.getByText(/候选资料限制：无有效正数挂牌价/)).toBeVisible();
});

test("product evidence has a market entry and navigation gains no new primary market page", async ({ page }) => {
  await fixture(page);
  await page.goto("/projects/10?view=shortlist");
  await page.getByRole("button", { name: /查看商品与证据/ }).first().click();
  const detail = page.getByRole("dialog", { name: "商品与卖家证据", exact: true });
  await detail.getByRole("button", { name: /查看行情参考/ }).click();
  await expect(detail).toBeHidden();
  await expect(page.getByLabel("挂牌价核心统计")).toContainText("9可用挂牌样本");
  await expect(page.getByRole("navigation", { name: "当前项目" }).getByRole("button", { name: "市场", exact: true })).toHaveCount(0);
});

test("camera models use their own comparison dimensions instead of requiring laptop attributes", async ({ page }) => {
  await fixture(page, "camera");
  await page.goto("/projects/10?view=products&display=market&marketFor=101");
  await expect(page.getByLabel("行情商品系列", { exact: true })).toHaveValue("Sony A7III");
  await expect(page.getByLabel("行情处理器 / 芯片", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("行情运行内存", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("挂牌价核心统计")).toContainText("1可用挂牌样本");
});

for (const display of ["table", "cards"]) test(`${display} product context restores filters, sort, page and scroll through reload and browser history`, async ({ page }) => {
  const data = await fixture(page, "many");
  await page.goto(`/projects/10?view=products&display=${display}&q=MacBook&state=evaluated&sort=price&page=1&fields=hidden`);
  const product = page.locator(display === "table" ? ".sp-table .sp-product-cell" : ".sp-products-grid .sp-title-button").nth(30);
  await product.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => window.scrollY);
  expect(before).toBeGreaterThan(100);
  await product.click();
  const detail = page.getByRole("dialog", { name: "商品与卖家证据", exact: true });
  await detail.getByRole("button", { name: /查看行情参考/ }).click();
  await expect(page.getByRole("heading", { name: /市场行情参考/ })).toBeVisible();
  await page.reload();
  await page.getByRole("link", { name: "返回商品列表", exact: true }).click();
  const search = new URL(page.url()).searchParams;
  for (const [key, value] of Object.entries({ view: "products", display, q: "MacBook", state: "evaluated", sort: "price", page: "1", fields: "hidden" })) expect(search.get(key)).toBe(value);
  await expect(page.getByRole("textbox", { name: "搜索商品", exact: true })).toHaveValue("MacBook");
  await expect(page.getByLabel("研究状态筛选", { exact: true })).toHaveValue("evaluated");
  await expect(page.getByLabel("商品排序", { exact: true })).toHaveValue("price");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeCloseTo(before, 0);
  await page.goBack();
  await expect(page.getByRole("link", { name: "返回商品列表", exact: true })).toBeVisible();
  await page.goForward();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeCloseTo(before, 0);
  expect(data.writes).toEqual([]);
});

test("shortlist and overview return to their origin while a direct or unsafe URL falls back to the product list", async ({ page }) => {
  const data = await fixture(page);
  await page.goto("/projects/10?view=shortlist");
  await page.locator(".ux2-decision-card details").first().locator("summary").click();
  await page.getByRole("link", { name: /查看行情参考/ }).first().click();
  await page.reload();
  await page.getByRole("link", { name: "返回候选清单", exact: true }).click();
  await expect(page.getByRole("heading", { name: "候选来源", exact: true })).toBeVisible();
  await page.goto("/projects/10?view=overview");
  await page.getByRole("link", { name: "查看挂牌行情", exact: true }).click();
  await page.getByRole("link", { name: "返回研究概览", exact: true }).click();
  await expect(page.getByRole("heading", { name: "目前，应该怎样选？", exact: true })).toBeVisible();
  for (const extra of ["", "&returnTo=https%3A%2F%2Fexample.com", "&returnTo=%2Fprojects%2F999%3Fview%3Dshortlist"]) {
    await page.goto(`/projects/10?view=products&display=market&marketFor=101${extra}`);
    const back = page.getByRole("link", { name: "返回商品列表", exact: true });
    await expect(back).toHaveAttribute("href", "/projects/10?view=products&display=table");
    await back.click(); await expect(page.getByRole("button", { name: "表格", exact: true })).toHaveAttribute("aria-pressed", "true");
  }
  expect(data.writes).toEqual([]);
});

test("overview all-candidates entry returns to overview, including a nested market visit and refresh", async ({ page }) => {
  const data = await fixture(page);
  await page.goto("/projects/10?view=overview");
  const all = page.getByRole("main").getByRole("button", { name: "候选清单", exact: true });
  await all.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => window.scrollY);
  await all.click();
  await expect(page.getByRole("heading", { name: "候选来源", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回研究概览", exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("checkbox", { name: /^对比 / }).first().click();
  await expect(page.getByRole("checkbox", { name: /^对比 / }).first()).toBeChecked();
  await page.locator(".ux2-decision-card details").first().locator("summary").click();
  await page.getByRole("link", { name: /查看行情参考/ }).first().click();
  await page.reload();
  await page.getByRole("link", { name: "返回候选清单", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /^对比 / }).first()).toBeChecked();
  await page.getByRole("link", { name: "返回研究概览", exact: true }).click();
  await expect(page.getByRole("heading", { name: "目前，应该怎样选？", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeCloseTo(before, 0);
  await page.goBack();
  await expect(page.getByRole("link", { name: "返回研究概览", exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole("heading", { name: "目前，应该怎样选？", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "当前项目" }).getByRole("button", { name: "候选清单", exact: true }).click();
  await expect(page.getByRole("link", { name: "返回研究概览", exact: true })).toHaveCount(0);
  expect(data.writes).toEqual([]);
});

test("settings and legacy detours keep the source including market conditions and refresh", async ({ page }) => {
  const data = await fixture(page);
  await page.goto("/projects/10?view=products&display=market&marketFor=101&market_storage=__all");
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.getByRole("navigation", { name: "系统配置" }).getByRole("button", { name: "闲鱼账户", exact: true }).click();
  await page.reload();
  await page.getByRole("link", { name: "返回行情分析", exact: true }).click();
  await expect(page.getByLabel("行情存储容量", { exact: true })).toHaveValue("__all");
  await page.getByText("统计口径、排除与证据局限", { exact: true }).click();
  await page.getByRole("link", { name: "查看原有市场统计与采集诊断 ↗", exact: true }).click();
  await page.getByRole("link", { name: "返回行情分析", exact: true }).click();
  await expect(page.getByLabel("行情存储容量", { exact: true })).toHaveValue("__all");
  await page.getByText("统计口径、排除与证据局限", { exact: true }).click();
  await page.getByRole("link", { name: "查看原有市场统计与采集诊断 ↗", exact: true }).click();
  await page.reload();
  await page.getByRole("link", { name: "返回行情分析", exact: true }).click();
  expect(data.writes).toEqual([]);
});

test("cancel monitor plan preserves source and Agent configuration requests remain drafts", async ({ page }) => {
  const {writes}=await fixture(page);
  await page.goto('/projects/10?view=monitors');
  await page.getByRole('button',{name:'新建监控',exact:true}).click();
  const plan=page.getByRole('dialog',{name:'监控计划草案',exact:true});
  await plan.getByRole('button',{name:'关闭监控计划草案',exact:true}).click();
  await page.goto('/projects/10?view=products&display=cards&q=M2&sort=price');
  await page.getByRole('button',{name:'打开项目 Agent'}).click();
  const agent=page.getByRole('complementary',{name:'SecondPick Agent 对话栏'});
  await agent.getByRole('textbox',{name:'给 Agent 的指令'}).fill('新建 Intel iMac 长期监控');
  await agent.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByLabel('调整哪项监控')).toBeVisible();
  await expect(page.getByRole('textbox',{name:'搜索商品',exact:true})).toHaveValue('M2');
  expect(writes).toEqual([]);
});

test("shared Agent requires confirmation and retries exact selected scope idempotently",async({page})=>{
  await fixture(page);const bodies:any[]=[];
  await page.route('**/api/projects/10/studies',async r=>{bodies.push(r.request().postDataJSON());await r.fulfill(bodies.length===1?{status:503,json:{error:{code:'offline',message:'Synthetic unavailable'}}}:{json:{id:901}})});
  await page.goto('/projects/10?view=products&q=Intel&sort=price');
  const boxes=page.getByRole('checkbox',{name:/^选择 /});await boxes.nth(0).check();await boxes.nth(1).check();
  await page.getByRole('button',{name:'AI 分析选中商品',exact:true}).click();
  const agent=page.getByRole('complementary',{name:'SecondPick Agent 对话栏'});
  await agent.getByRole('textbox',{name:'给 Agent 的指令'}).fill('深入调查这些商品');
  await agent.getByRole('button',{name:'发送',exact:true}).click();
  await expect(agent).toContainText('#111、#112');expect(bodies).toEqual([]);
  const confirm=agent.getByRole('button',{name:'确认并创建研究任务'});await confirm.click();
  await expect(agent.getByRole('alert')).toContainText('Synthetic unavailable');await confirm.click();
  await expect(agent).toContainText('研究 #901 已创建');expect(bodies).toHaveLength(2);
  expect(bodies[0].ids).toEqual([111,112]);expect(bodies[0].request_key).toBe(bodies[1].request_key);
  expect(bodies[0].expected_goal_revision).toBe(1);expect(bodies[0].question).toContain('不得更改持久研究策略');
  await agent.getByRole('button',{name:'收起 Agent'}).click();await expect(boxes.nth(0)).toBeChecked();
});

test("candidate comparison and report follow-up share chat with explicit evidence provenance",async({page})=>{
  await fixture(page);const turns:any[]=[];
  await page.route('**/api/projects/10/agent-chat',async r=>{if(r.request().method()==='POST'){turns.push(r.request().postDataJSON());await r.fulfill({json:{id:1}})}else await r.fulfill({json:{items:[]}})});
  await page.goto('/projects/10?view=shortlist&compare=101,102');
  await page.getByRole('button',{name:'向 Agent 提问',exact:true}).click();
  const agent=page.getByRole('complementary',{name:'SecondPick Agent 对话栏'});
  await expect(agent.getByRole('textbox',{name:'给 Agent 的指令'})).toHaveValue(/比较这些商品/);
  await agent.getByRole('button',{name:'发送',exact:true}).click();await expect.poll(()=>turns.length).toBe(1);
  expect(turns[0].ids).toEqual([101,102]);expect(turns[0].report_id).toBe(1);
  await page.goto('/projects/10?view=overview');await page.getByRole('button',{name:'带着结论继续问'}).click();
  await agent.getByRole('textbox',{name:'给 Agent 的指令'}).fill('为什么报告有这些结论？');
  await agent.getByRole('button',{name:'发送',exact:true}).click();await expect.poll(()=>turns.length).toBe(2);
  expect(turns[1].report_id).toBe(1);expect(turns[1].ids).toEqual([101]);
});

test("goal and monitor requests open explicit editing workflows without persistent writes",async({page})=>{
  const {writes}=await fixture(page);await page.goto('/projects/10?view=research');
  await page.getByRole('button',{name:'打开项目 Agent'}).click();
  const agent=page.getByRole('complementary',{name:'SecondPick Agent 对话栏'});
  await agent.getByRole('textbox',{name:'给 Agent 的指令'}).fill('把预算改为6000元');await agent.getByRole('button',{name:'发送',exact:true}).click();
  const goal=page.getByRole('dialog',{name:'调整选购条件',exact:true});await expect(goal.getByLabel('修改意图')).toHaveValue('把预算改为6000元');
  expect(writes).toEqual([]);page.once('dialog',d=>d.accept());await goal.getByRole('button',{name:'关闭调整选购条件'}).click();
  await agent.getByRole('textbox',{name:'给 Agent 的指令'}).fill('新建 Intel iMac 长期监控');await agent.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByLabel('调整哪项监控')).toBeVisible();expect(writes).toEqual([]);
});

test("oversized selection is not silently truncated and hiding Agent preserves keyboard workflow",async({page})=>{
  const {writes}=await fixture(page,'many');await page.goto('/projects/10?view=products');
  await page.getByRole('checkbox',{name:'全选当前页',exact:true}).check();await expect(page.getByRole('button',{name:'AI 分析选中商品',exact:true})).toBeDisabled();
  const launcher=page.getByRole('button',{name:'打开项目 Agent'});await launcher.click();
  const agent=page.getByRole('complementary',{name:'SecondPick Agent 对话栏'});
  await expect(agent).toContainText('商品范围暂不可用');
  await expect(agent.getByRole('button',{name:'发送',exact:true})).toBeDisabled();
  await agent.getByRole('button',{name:'收起 Agent'}).click();await expect(launcher).toBeVisible();expect(writes).toEqual([]);
});

test("seller analysis uses saved profile endpoint and truthfully reports cached result",async({page})=>{
  await fixture(page);let calls=0;
  const seller={seller_id:'synthetic-seller',profile:{},result:null,fresh:true,observed_at:null,researched_at:null};
  await page.route('**/api/projects/10/listings/101/seller',r=>r.fulfill({json:seller}));
  await page.route('**/api/projects/10/listings/101/seller/studies',async r=>{calls++;await r.fulfill({json:seller})});
  await page.goto('/projects/10?view=shortlist');await page.locator('.ux2-decision-card').first().getByRole('button',{name:'查看商品与证据',exact:true}).click();
  const drawer=page.getByRole('dialog',{name:'商品与卖家证据',exact:true});await drawer.getByRole('button',{name:'复用已有研究档案',exact:true}).click();
  await expect(drawer).toContainText('已复用该卖家的有效档案');await expect(drawer).toContainText('不自动访问卖家主页或补抓');expect(calls).toBe(1);
});
