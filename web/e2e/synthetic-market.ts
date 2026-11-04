import type { Page } from '@playwright/test';

// Public deterministic responses; no recorded accounts, listings or model output.
export async function syntheticMarket(page: Page, model = 'Synthetic Camera Z9', unknown = false) {
  const data = await (await page.request.get('/api/projects/10/overview')).json();
  data.project.goal = `Compare ${model}`;
  data.goal_context = {current_revision:1,original_goal:data.project.goal,report_current:true,calibration:'current',legacy_unmerged:false};
  data.cards = [100.5,110,120].map((price,i)=>({listing_id:101+i,title:`${model} synthetic sample ${i+1}`,price_value:price,price_text:String(price),url:`https://example.test/item/${101+i}`,image_url:null,source_run_ids:[],seller_name:null,location:null,detail_status:'not_captured',research_state:'waiting',search_condition:null}));
  const layer=(ids:number[])=>({count:ids.length,member_ids:ids,summary:{count:ids.length,min:ids.length?110:null,max:ids.length?120:null,median:ids.length?115:null,q1:ids.length?110:null,q3:ids.length?120:null},position:'样本少，不展示精确排名或价格评分'});
  data.market={comparison_version:2,groups:unknown?[]:[{key:model,model,label:model,member_ids:[101,102,103],summary:layer([101,102,103]).summary}],references:{'101':{target_id:101,as_of:'2026-11-03T00:00:00Z',current_quote:{valid:true,status:'valid',amount:'100.50',warnings:[]},model,criteria:{broad:'同一明确商品身份，配置可缺失',strict:'已保存属性明确相同'},broad:layer(unknown?[]:[102,103]),strict:layer(unknown?[]:[102]),peer_total:2,excluded_count:unknown?2:0,exclusion_counts:{},excluded:[],strict_excluded:[],unavailable_reason:unknown?'所售型号未明确':null,limitations:['挂牌不是成交价；不是 AI 已更新的研究结论'],data_digest:'synthetic-only'}}};
  data.total=3;data.favorites=[101];data.studies=[];data.report=null;data.policy={...data.policy,paused:1,auto_research:0};
  await page.route('**/api/projects/10/overview',route=>route.fulfill({json:data}));
  const original=await(await page.request.get('/api/listings/1/evidence?task_id=1')).json();
  await page.route('**/api/listings/101/evidence?*',route=>route.fulfill({json:{...original,...data.cards[0],has_detail:false,detail:null}}));
  await page.route('**/api/tasks/10/listings/101/images',route=>route.fulfill({json:{listing_id:101,images:[]}}));
  return data;
}
