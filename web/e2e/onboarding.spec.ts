import {expect,test,type Page} from '@playwright/test';

// Readiness is a response fixture, never a real account or CLI probe.
async function readiness(page:Page,{empty=false,ai=false,completed=false}={}) {
  let done=completed;
  const patches:unknown[]=[];
  if(empty)await page.route('**/api/tasks?*',r=>r.fulfill({json:{items:[],total_count:0}}));
  await page.route('**/api/settings',async r=>{
    const original=await(await r.fetch()).json();
    if(r.request().method()==='PATCH'){patches.push(r.request().postDataJSON());done=true;}
    await r.fulfill({json:{...original,setup_completed:done,setup_mode:'basic'}});
  });
  await page.route('**/api/setup/status',r=>r.fulfill({json:{setup_completed:done,environment:[{name:'config',ok:true,detail:'synthetic'},{name:'database',ok:true,detail:'temporary'}],codex:{cli_available:ai,auth_available:ai,process_running:false,detail:'Offline fixture'},xianyu:{profile_present:false,auth_status:'unknown'},can_browse_existing_data:true,can_start_research:false}}));
  await page.route('**/api/browser/status',r=>r.fulfill({json:{auth_status:'verified',enabled:true,max_pages:3,active_job:null,login_job:null}}));
  await page.route('**/api/monitor-engine/check',r=>r.fulfill({json:r.request().method()==='GET'?{result:{ready:true,checks:[{code:'configuration',ok:true}],checked_at:new Date().toISOString()}}:{ready:true,checks:[{code:'configuration',ok:true}],checked_at:new Date().toISOString()}}));
  return patches;
}
const steps=(page:Page)=>page.getByRole('navigation',{name:'使用引导步骤'});
test.afterEach(async({page})=>page.unrouteAll({behavior:'wait'}));

test('missing engine has installation guidance and recheck can confirm readiness without installation side effects', async ({page}) => {
  await readiness(page);
  const actions:string[]=[];
  page.on('request', request => { if(request.method()==='POST') actions.push(new URL(request.url()).pathname); });
  await page.route('**/api/monitor-engine/check', route => {
    const ready=route.request().method()==='POST';
    const result={ready,checked_at:new Date().toISOString(),checks:[{code:'configuration',ok:true},{code:'source',ok:ready}]};
    return route.fulfill({json:ready?result:{result}});
  });
  await page.goto('/onboarding?step=0');
  await expect(page.getByText('采集引擎尚未安装',{exact:true})).toBeVisible();
  await expect(page.getByText('python scripts/setup_monitor.py',{exact:true})).toBeVisible();
  await expect(page.getByText('引擎版本兼容性',{exact:true})).toHaveCount(0);
  expect(actions).toEqual([]);
  await page.getByRole('button',{name:'检查采集引擎环境',exact:true}).click();
  await expect(page.getByText('环境检查通过',{exact:true})).toBeVisible();
  expect(actions).toEqual(['/api/monitor-engine/check']);
});

test('settings reads local status without starting platform or model actions',async({page})=>{
  const writes:string[]=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url())});
  await page.goto('/settings?section=codex');
  await expect(page.getByRole('heading',{name:'系统设置',exact:true})).toBeVisible();
  await expect(page.getByText('后端已连接',{exact:true})).toBeVisible();
  await expect(page.locator('.ss-row').filter({hasText:'版本与当前运行状态'}).getByText('未知',{exact:true})).toBeVisible();
  expect(writes).toEqual([]);
});
test('first run preserves mode and step across dismissal and reload',async({page})=>{
  await readiness(page,{empty:true});await page.goto('/');
  await expect(page).toHaveURL(/onboarding/);
  await expect(page).toHaveURL(/capability=basic/);
  await page.getByRole('radio',{name:'AI 增强模式',exact:true}).click();await expect(page.getByRole('radio',{name:'AI 增强模式',exact:true})).toBeChecked();
  await steps(page).getByRole('button',{name:/AI 驱动/}).click();
  await expect(page.getByRole('heading',{name:'检查 AI 研究驱动'})).toBeVisible();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'暂时关闭',exact:true}).click();
  await page.reload();await expect(page).not.toHaveURL(/onboarding/);
  await page.getByRole('link',{name:/首次配置尚未完成/}).click();
  await expect(page.getByRole('heading',{name:'检查 AI 研究驱动'})).toBeVisible();
});
test('Basic completion requires no CLI and only saves mode and completion before opening creator',async({page})=>{
  const patches=await readiness(page,{empty:true});await page.goto('/onboarding');
  await steps(page).getByRole('button',{name:/就绪检查/}).click();
  await expect(steps(page).getByRole('button',{name:/AI 驱动/})).toHaveCount(0);
  await page.getByRole('button',{name:'完成基础配置并开始使用'}).click();
  await expect(page.getByRole('dialog',{name:'新建选购项目'})).toBeVisible();
  expect(patches).toEqual([{setup_completed:true,setup_mode:'basic'}]);
  await expect(page.getByRole('textbox',{name:'选购目标',exact:true})).toBeVisible();
});
test('AI mode adds CLI authorization readiness and does not silently fall back to Basic',async({page})=>{
  await readiness(page);await page.goto('/onboarding?capability=ai&step=3');
  await expect(page.getByRole('button',{name:'完成 AI 增强配置并开始使用'})).toBeDisabled();
  await page.reload();await expect(page.getByRole('radio',{name:'AI 增强模式',exact:true})).toBeChecked();
  await expect(page.getByRole('button',{name:'完成 AI 增强配置并开始使用'})).toBeDisabled();
});
test('authorized synthetic AI readiness completes without research authorization or vision',async({page})=>{
  const patches=await readiness(page,{ai:true});const writes:string[]=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url())});
  await page.goto('/onboarding?capability=ai&step=3');
  await page.getByRole('button',{name:'完成 AI 增强配置并开始使用'}).click();
  await expect(page).toHaveURL('/');expect(patches).toEqual([{setup_completed:true,setup_mode:'ai'}]);expect(writes).toEqual([]);
});
test('settings review starts at first step and preserves exact return location and browser history',async({page})=>{
  const patches=await readiness(page,{completed:true});const source='/settings?section=codex&returnTo=%2Fprojects%2F1%3Fview%3Dproducts';
  await page.goto(source);await page.getByRole('link',{name:'使用引导',exact:true}).click();
  await expect(page.getByRole('heading',{name:'准备基础与采集环境'})).toBeVisible();
  await steps(page).getByRole('button',{name:/闲鱼连接/}).click();await page.reload();
  await expect(page.getByRole('heading',{name:'连接闲鱼账户'})).toBeVisible();
  await page.goBack();await expect(page.getByRole('heading',{name:'准备基础与采集环境'})).toBeVisible();
  await page.goForward();await page.getByRole('button',{name:'暂时关闭',exact:true}).click();await expect(page).toHaveURL(source);expect(patches).toEqual([]);
});
test('unsafe wizard return cannot leave workbench',async({page})=>{
  await readiness(page);await page.goto('/onboarding?returnTo=https%3A%2F%2Fexample.com&step=3');
  // Wait for the mocked readiness responses; closing before they arrive asks
  // for confirmation and the browser dismisses an unhandled dialog.
  await expect(page.getByRole('button',{name:'完成基础配置并开始使用'})).toBeEnabled();
  await page.getByRole('button',{name:'暂时关闭',exact:true}).click();await expect(page).toHaveURL('/');
});
test('unfinished configuration opened from a project restores its filters',async({page})=>{
  await readiness(page);const source='/projects/10?view=products&display=cards&q=ThinkPad&sort=price&page=1';
  await page.goto(source);await page.getByRole('link',{name:/首次配置/}).click();
  await steps(page).getByRole('button',{name:/闲鱼连接/}).click();await page.reload();
  await page.getByRole('button',{name:'暂时关闭',exact:true}).click();await expect(page).toHaveURL(source);
});
test('failed browser status stays unknown and cannot open login',async({page})=>{
  await page.route('**/api/browser/status',r=>r.fulfill({status:503,json:{error:{code:'unavailable',message:'连接状态服务暂不可用'}}}));
  await page.goto('/settings?section=xianyu');await expect(page.getByRole('alert')).toContainText('闲鱼状态暂不可用');
  await expect(page.getByRole('button',{name:'打开闲鱼登录窗口'})).toBeDisabled();
});
test('failed completion keeps readiness and never acknowledges saved settings',async({page})=>{
  await readiness(page);await page.route('**/api/settings',r=>r.request().method()==='PATCH'?r.fulfill({status:503,json:{error:{code:'write_failed',message:'无法保存配置记录'}}}):r.fallback());
  await page.goto('/onboarding?step=3');await page.getByRole('button',{name:'完成基础配置并开始使用'}).click();
  await expect(page.getByRole('alert')).toContainText('无法保存配置记录');await expect(page.getByRole('heading',{name:'确认当前可用能力'})).toBeVisible();
});
test('diagnostics invokes only explicitly requested checks',async({page})=>{
  await readiness(page);const actions:string[]=[];page.on('request',r=>{if(r.method()==='POST')actions.push(new URL(r.url()).pathname)});
  await page.goto('/settings?section=diagnostics');await page.getByRole('button',{name:'检查应用基础环境',exact:true}).click();
  await expect.poll(()=>actions.length).toBe(1);await page.getByRole('button',{name:'检查采集引擎环境',exact:true}).click();
  await expect.poll(()=>actions.length).toBe(2);expect(actions).toEqual(['/api/setup/check-environment','/api/monitor-engine/check']);
});
test('offline login job restores after reload and is explicitly cancelled',async({page})=>{
  await page.goto('/settings?section=xianyu');await page.getByRole('button',{name:/打开.*登录窗口/}).click();
  await expect(page.getByRole('button',{name:'我已登录，验证连接'})).toBeEnabled();await page.reload();
  await page.getByRole('button',{name:'取消登录任务'}).click();await expect(page.locator('.ss-notice').filter({hasText:'登录任务 #'})).toContainText('cancelled');
  await expect.poll(async()=>(await(await page.request.get('/api/browser/status')).json()).active_job).toBeNull();
});
test('expired account and unavailable CLI authorization remain separate',async({page})=>{
  await readiness(page);await page.route('**/api/browser/status',r=>r.fulfill({json:{auth_status:'invalid',enabled:true,max_pages:3,active_job:null,login_job:null}}));
  await page.route('**/api/setup/status',async r=>{const d=await(await r.fetch()).json();await r.fulfill({json:{...d,codex:{cli_available:true,auth_available:false,process_running:false,detail:'authentication required'}}})});
  await page.goto('/settings');await expect(page.getByText('需要重新登录',{exact:true})).toBeVisible();await expect(page.getByText('授权未通过',{exact:true})).toBeVisible();
});
test('settings and wizard fit supported desktop viewports',async({page})=>{
  for(const width of [1440,1280,1024]){await page.setViewportSize({width,height:900});for(const url of ['/settings','/settings?section=xianyu','/onboarding']){await page.goto(url);await expect(page.getByRole('main')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)}}
});
