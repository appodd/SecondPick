import { expect, test, type Page } from "@playwright/test";

// Explicit, isolated acceptance records; never written to the user's database.
async function fixture(page: Page, versioned = false) {
  let legacy = false, unavailable = false;
  const original = "购买二手MacBook Pro，优先M系列，成色好，性价比高";
  const revised = "MacBook Pro，必须至少16GB内存，预算不超过5000元，仍优先M系列";
  const titles = ["MacBook Pro M1 Pro 16GB 1TB", "MacBook Pro M2 16GB 512GB", "MacBook Pro M2 8GB 256GB", "MacBook Pro M1 8GB 512GB", "MacBook Pro M2 配置待核实", "MacBook Pro M2 32GB 512GB"];
  const ids = [143, 385, 378, 366, 1005, 1006], prices = [6000, 5666, 4090, 3400, 4000, 4500];
  await page.route("**/api/projects/10/overview", async route => {
    const response = await route.fetch(), data = await response.json();
    delete data.goal_context; if(versioned)data.goal_context={current_revision:1,report_current:true,calibration:"current",legacy_unmerged:false}; data.project.goal = original; data.policy = { ...data.policy, budget: null, hard: [], soft: ["优先M系列"], paused: 0, auto_research: 1 };
    data.cards = ids.map((listing_id, i) => ({ listing_id, title: titles[i], price_value: prices[i], price_text: String(prices[i]), url: "https://www.goofish.com/item", research_state: "evaluated", detail_status: "not_captured", source_run_ids: [], location: null, seller_name: null, search_condition: null }));
    data.total = 6; data.coverage = { evaluated: 6, waiting: 0, under_ai: 0, summarized: 0, needs_information: 0, rule_excluded: 0, blocked: 0 }; data.favorites = [143];
    data.report = { id: 70, study_id: 700, content: "原目标下的历史报告，所有价格均为保存记录。", candidate_ids_json: "[143,385,378,366]", snapshot_at: "2026-10-22T00:00:00Z", created_at: "2026-10-22T00:01:00Z", limited: 1 };
    data.studies = [{ id: 701, kind: "incremental", state: "running", listing_ids: [143], snapshot_at: "2026-10-22T00:02:00Z", created_at: "2026-10-22T00:02:00Z", finished_at: null, result: null, error: null }, { id: 700, kind: "initial", state: "completed", listing_ids: ids.slice(0, 4), snapshot_at: "2026-10-22T00:00:00Z", created_at: "2026-10-22T00:00:00Z", finished_at: "2026-10-22T00:01:00Z", result: { content: data.report.content, candidate_ids: ids.slice(0, 4) }, error: null }];
    await route.fulfill({ json: data });
  });
  await page.route("**/api/tasks/10", async route => {
    if (unavailable) return route.fulfill({ status: 503, json: { error: { code: "offline", message: "目标记录服务不可用" } } });
    const response = await route.fetch(), data = await response.json();
    data.task.goal = data.task.original_goal = original; data.task.effective_goal = legacy ? revised : original;
    data.preference_revision_id = legacy ? 9 : 0;
    data.preference_revisions = legacy ? [{ id: 9, task_id: 10, user_message: revised, effective_goal: revised, added_preferences: ["至少16GB", "预算5000"], removed_preferences: [], created_at: "2026-10-23T00:00:00Z" }] : [];
    await route.fulfill({ json: data });
  });
  const writes: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/") && request.method() !== "GET") writes.push(request.url()); });
  return { writes, revised, change: () => { legacy = true; }, fail: () => { unavailable = true; } };
}
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: "wait" }); });

test('current research state follows server queue, execution, failure and completed result',async({page})=>{
  let state='queued';
  await page.route('**/api/projects/10/overview',async r=>{
    const d=await(await r.fetch()).json();d.goal_context={current_revision:2,original_goal:d.project.goal,report_current:state==='completed',calibration:state==='completed'?'current':'pending',legacy_unmerged:false};
    d.studies=[{id:230,origin:'automatic_calibration',kind:'initial',state,goal_revision:2,listing_ids:[],created_at:'2026-11-03',snapshot_at:'2026-11-03',error:state==='failed'?'Synthetic quota error':null,result:state==='completed'?{content:'Synthetic completed calibration',candidate_ids:[]}:null}];
    await r.fulfill({json:d});
  });
  for(const [value,kind]of[['queued','waiting'],['running','running'],['failed','attention'],['completed','success']]){
    state=value;await page.goto('/projects/10?view=research');
    await expect(page.locator('.sp-research-featured .sp-status')).toHaveAttribute('data-kind',kind);
    await expect(page.getByRole('heading',{name:'研究 #230 · 目标校准',exact:true})).toBeVisible();
  }
  await expect(page.locator('.sp-research-featured')).toContainText('Synthetic completed calibration');
});

test('goal preview checks budget and memory without saving, collecting or invoking AI',async({page})=>{
  const data=await fixture(page,true);await page.goto('/projects/10?view=overview');
  await page.getByRole('link',{name:'调整目标 →'}).click();
  const dialog=page.getByRole('dialog',{name:'调整选购条件',exact:true});await dialog.getByRole('button',{name:'直接手动修改'}).click();
  await dialog.getByLabel('调整后的选购目标',{exact:true}).fill(data.revised);
  await dialog.getByLabel('拟定预算上限（元）',{exact:true}).fill('5000');await dialog.getByLabel('拟定最低内存（GB）',{exact:true}).fill('16');
  await dialog.getByRole('button',{name:'预览调整影响',exact:true}).click();const impact=dialog.getByRole('region',{name:'目标调整影响预览'});
  await impact.getByText('展开商品核对详情',{exact:true}).click();
  await expect(impact).toContainText('原报告可读取候选 4 件，其中 4 件按保存记录不满足拟定条件');
  await expect(impact.locator('.sp-goal-impact-list').first().getByText('按已保存挂牌价超出拟定预算',{exact:true})).toHaveCount(2);
  await expect(impact.locator('.sp-goal-impact-list').first().getByText(/按标题自述 8GB，低于拟定的 16GB/)).toHaveCount(2);
  await expect(dialog.locator('.sp-goal-counts')).toHaveText('4按记录不满足1信息待核实1已知条件暂符合');
  await expect(dialog.getByRole('button',{name:'确认并保存修改',exact:true})).toBeEnabled();expect(data.writes).toEqual([]);
  await dialog.getByLabel('拟定预算上限（元）',{exact:true}).fill('7000');await expect(impact).toHaveCount(0);
  page.once('dialog',d=>d.accept());await page.keyboard.press('Escape');await page.reload();await expect(page.locator('.sp-project-goal-text')).toHaveText('购买二手MacBook Pro，优先M系列，成色好，性价比高');expect(data.writes).toEqual([]);
});

test('legacy goal revision preserves report as history and does not relabel active study',async({page})=>{
  const data=await fixture(page);data.change();await page.goto('/projects/10?view=overview');
  await expect(page.locator('.sp-current-report')).toHaveClass(/sp-report-historical/);await expect(page.locator('.sp-overview-caution')).toContainText('历史参考');
  await page.locator('summary').filter({hasText:'运行详情'}).click();await expect(page.getByText('当前目标下已评估数量暂不可确认。',{exact:false})).toBeVisible();
  await page.getByRole('navigation',{name:'当前项目',exact:true}).getByRole('button',{name:'Agent 研究',exact:true}).click();
  await expect(page.getByRole('heading',{name:'研究 #701 · 增量研究',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'研究下一个有限批次',exact:true})).toBeDisabled();
  await page.getByRole('navigation',{name:'当前项目',exact:true}).getByRole('button',{name:'候选清单',exact:true}).click();
  await expect(page.getByRole('region',{name:'候选来源与新鲜度'})).toContainText('适用性待确认');
  await expect(page.getByRole('button',{name:'取消收藏商品 #143',exact:true})).toBeVisible();expect(data.writes).toEqual([]);
});

test('unavailable goal record prevents research and keeps saved report unconfirmed',async({page})=>{
  const data=await fixture(page);data.fail();await page.goto('/projects/10?view=research');
  await expect(page.getByRole('button',{name:'研究下一个有限批次',exact:true})).toBeDisabled();
  await page.goto('/projects/10?view=overview');await expect(page.locator('.sp-current-report')).toHaveClass(/sp-report-historical/);
  await expect(page.locator('.sp-overview-caution')).toContainText('暂不可确认');expect(data.writes).toEqual([]);
});

test('losing goal confirmation never promotes a historical report to current recommendation',async({page})=>{
  const data=await fixture(page);data.change();await page.goto('/projects/10?view=overview');await expect(page.locator('.sp-overview-caution')).toContainText('历史参考');
  data.fail();await expect(page.locator('.sp-overview-caution')).toContainText('暂不可确认',{timeout:10000});await expect(page.locator('.sp-current-report')).toHaveClass(/sp-report-historical/);expect(data.writes).toEqual([]);
});

test("NS2 controller confirms a real goal version without computer fields, duplicate versions, research or monitor changes", async ({ page }) => {
  const original="找二手NS2 Pro手柄，价格合适";
  const created=await page.request.post("/api/projects",{ data:{ title:"二手NS2 Pro手柄",goal:original,hard:[],soft:[],auto_research:false } });
  const id=(await created.json()).id;
  const requests: { request_key: string }[]=[];
  await page.route(`**/api/projects/${id}/goal`,async route => {
    requests.push(route.request().postDataJSON());
    const response=await route.fetch();
    if(requests.length===1) { await new Promise(resolve => setTimeout(resolve,5500)); await route.fulfill({status:503,json:{error:{code:"lost_response",message:"测试保存响应丢失，请重试"}}}); }
    else await route.fulfill({response});
  });
  const aiWrites:string[]=[];
  page.on("request",request=>{if(request.method()!=="GET" && /studies|monitor-drafts|project-goal-drafts|\/monitors/.test(request.url())) aiWrites.push(request.url());});
  await page.goto(`/projects/${id}?view=overview`);
  await page.getByRole("link",{name:"调整目标 →",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"调整选购条件",exact:true});
  await dialog.getByRole("button",{name:"直接手动修改",exact:true}).click();
  await expect(dialog.getByLabel("拟定最低内存（GB）",{exact:true})).toHaveCount(0);
  await dialog.getByLabel("调整后的选购目标",{exact:true}).fill("原装二手NS2 Pro手柄，预算350元");
  await dialog.getByLabel("拟定预算上限（元）",{exact:true}).fill("350");
  await dialog.getByLabel("保留的硬条件（每行一项）",{exact:true}).fill("必须兼容Switch 2");
  await dialog.getByRole("button",{name:"预览调整影响",exact:true}).click();
  await dialog.getByRole("button",{name:"确认并保存修改",exact:true}).click();
  await expect(dialog.getByRole("alert")).toContainText("响应丢失", { timeout: 15000 });
  await dialog.getByRole("button",{name:"确认并保存修改",exact:true}).click();
  await expect(dialog).toContainText("已从 v1 更新为 v2");
  expect(requests).toHaveLength(2); expect(requests[0].request_key).toBe(requests[1].request_key);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading",{name:"当前选购目标 v2",exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading",{name:"当前选购目标 v2",exact:true})).toBeVisible();
  const data=await(await page.request.get(`/api/projects/${id}/overview`)).json();
  expect(data.goal_context.original_goal).toBe(original); expect(data.policy.auto_research).toBe(0);
  expect(data.policy.hard).toEqual(["必须兼容Switch 2"]); expect(data.studies).toEqual([]);
  expect((await(await page.request.get(`/api/tasks/${id}/monitors`)).json()).items).toEqual([]);
  expect(aiWrites).toEqual([]);
});

test("an outdated confirmation returns a conflict and preserves the user's unsaved draft", async ({ page }) => {
  const response=await page.request.post("/api/projects",{data:{title:"未知品类",goal:"二手收藏品，优先16GB",hard:[],soft:[]}});
  const id=(await response.json()).id;
  const baseline=await(await page.request.get(`/api/projects/${id}/overview`)).json();
  await page.route(`**/api/projects/${id}/overview`,route=>route.fulfill({json:baseline}));
  await page.goto(`/projects/${id}`);
  await page.getByRole("link",{name:"调整目标 →",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"调整选购条件",exact:true});
  await dialog.getByRole("button",{name:"直接手动修改",exact:true}).click();
  await expect(dialog.getByLabel("拟定最低内存（GB）",{exact:true})).toHaveCount(0);
  await expect(dialog.getByLabel("保留的硬条件（每行一项）",{exact:true})).toHaveValue("");
  await dialog.getByLabel("调整后的选购目标",{exact:true}).fill("此窗口的未保存草案");
  await dialog.getByRole("button",{name:"预览调整影响",exact:true}).click();
  await page.request.patch(`/api/projects/${id}/goal`,{data:{goal:"另一窗口已确认目标",budget:null,hard:[],soft:[],expected_revision:1,request_key:"another-browser-confirm",confirmed:true}});
  await dialog.getByRole("button",{name:"确认并保存修改",exact:true}).click();
  await expect(dialog.getByRole("alert")).toContainText("已变化");
  await expect(dialog.getByLabel("调整后的选购目标",{exact:true})).toHaveValue("此窗口的未保存草案");
  expect((await(await page.request.get(`/api/projects/${id}/overview`)).json()).project.goal).toBe("另一窗口已确认目标");
});

test("a versioned old running study stays historical and report history retains its goal provenance", async ({ page }) => {
  await page.route("**/api/projects/10/overview",async route=>{
    const response=await route.fetch(),data=await response.json();
    data.goal_context={current_revision:2,original_goal:data.project.goal,report_current:false,calibration:"pending",legacy_unmerged:false,automatic_calibration_supported:false,updated_at:"2026-10-23T00:00:00Z"};
    data.report={id:42,study_id:701,goal_revision:1,content:"目标v1的真实历史字段测试文本",candidate_ids_json:"[]",snapshot_at:"2026-10-22T00:00:00Z",created_at:"2026-10-22T00:01:00Z",limited:1};
    data.studies=[{id:701,goal_revision:1,kind:"incremental",state:"running",listing_ids:[],snapshot_at:"2026-10-22T00:00:00Z",created_at:"2026-10-22T00:00:00Z",result:null,error:null}];
    await route.fulfill({json:data});
  });
  await page.route("**/api/projects/10/reports",route=>route.fulfill({json:{items:[{id:42,goal_revision:1,content:"目标v1的真实历史字段测试文本",candidate_ids_json:"[]",snapshot_at:"2026-10-22T00:00:00Z",created_at:"2026-10-22T00:01:00Z",limited:1}],has_more:false,next_before_id:null}}));
  await page.goto("/projects/10?view=research");
  await expect(page.locator(".sp-research-featured")).toContainText("历史目标结果");
  await expect(page.getByText("正在按目标 v2 研究",{exact:true})).toHaveCount(0);
  await page.getByText("任务详情与证据",{exact:true}).click();
  await expect(page.getByText(/目标 v1（历史目标，不覆盖当前结论）/)).toBeVisible();
  await page.getByText("历史研究报告",{exact:true}).click();
  await page.getByRole("button",{name:/报告 #42 · 目标 v1/}).click();
  const reader=page.getByRole("dialog",{name:"完整研究报告",exact:true});
  await expect(reader).toContainText("本报告基于目标 v1");
});
