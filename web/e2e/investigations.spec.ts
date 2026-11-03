import { expect, test } from "@playwright/test";
test("P1 scoped approval, results, refresh and narrow layout without AI", async ({ page }, info) => {
  let calls = 0, planned = false;
  let item = { id: 1, listing_id: 1879, goal_revision: 1, kind: "detail", state: "pending", outdated: false, job_id: null as number | null, job_state: null as string | null, stage: null as string | null, error_code: null,
    plan: { title: "隔离模拟 NS2 Pro 手柄", objective: "补充公开描述与图片链接", reason: "历史研究提名；关键公开证据缺失", evidence_gaps: ["完整描述"], expected_information: ["完整描述", "图片链接"], capability: "现有 BrowserJob 商品详情采集", manual_questions: ["能否提供摇杆测试视频？"], seller_public_questions: ["卖家主页公开评价"], source_study_ids: [49] }, outcome: {} };
  const result = () => ({ items: planned ? [item] : [], skipped: [], max_listings: 3, automatic_research_held: item.state === "new_evidence" });
  await page.route("**/api/projects/10/investigations**", async route => {
    const url = route.request().url();
    if (route.request().method() === "POST") {
      if (url.endsWith("/plan")) planned = true;
      if (url.endsWith("/approve")) { expect(route.request().postDataJSON()).toEqual({ confirmed: true }); item = { ...item, state: "approved" }; }
      if (url.endsWith("/execute")) { calls++; expect(route.request().postDataJSON()).toEqual({ confirmed: true }); item = { ...item, state: "new_evidence", job_id: 91, job_state: "completed", stage: "completed", outcome: { new_evidence: true, detail_snapshot_ids: [301] } }; }
    }
    await route.fulfill({ json: result() });
  });
  await page.route("**/api/browser/jobs/91**", route => route.fulfill({ json: route.request().url().endsWith("/audit") ? { job_id:91,items:[],has_more:false } :
    { id:91,kind:"collection",task_id:10,request_id:5,retry_of:null,query:"",max_pages:1,actions:["detail"],listing_ids:[1879],state:"completed",stage:"completed",error_code:null,error_detail:null,result:{run_ids:[1],listing_count:1},verify_requested:false,stop_requested:false,created_at:"2026-10-24",completed_at:"2026-10-24",analysis_operation_id:null } }));
  let aiCalls = 0; page.on("request", req => { if (req.method()==="POST" && /\/studies(?:\?|$)/.test(req.url())) aiCalls++; });
  await page.goto("/projects/10?view=research");
  const panel=page.getByRole("region",{name:"调查建议与执行"});
  await panel.getByRole("button",{name:"整理已有研究的调查建议"}).click();
  await expect(panel.getByText("等待确认",{exact:true})).toBeVisible(); expect(calls).toBe(0);
  await panel.getByRole("button",{name:"批准本商品一次详情访问"}).click();
  await expect(panel.getByText("已批准，尚未执行",{exact:true})).toBeVisible(); expect(calls).toBe(0);
  await panel.getByRole("button",{name:"确认执行（仅 1 件详情）"}).click();
  await expect(panel.getByText("已获得新证据",{exact:true})).toBeVisible(); await expect(panel.getByText(/原报告和历史判断尚未/)).toBeVisible();
  await page.reload(); await expect(panel.getByText("已获得新证据",{exact:true})).toBeVisible(); expect(calls).toBe(1); expect(aiCalls).toBe(0);
  await panel.scrollIntoViewIfNeeded(); await page.screenshot({path:info.outputPath("p1-investigations.png")});
  expect(await page.evaluate(() => document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
});
