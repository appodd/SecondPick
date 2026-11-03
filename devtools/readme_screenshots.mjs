/** Capture the real UI with synthetic responses. No backend, credentials or platform traffic. */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'web/package.json'));
const { chromium } = require('playwright');
const staticRoot = path.join(root, 'src/shopping_agent/web/static');
const output = path.join(root, 'docs/images');
fs.mkdirSync(output, { recursive: true });
const now = '2026-11-01T08:30:00Z';
const goal = '想找一台二手 MacBook Pro，M2 或更新芯片，内存至少 16GB，预算 7000 元以内。希望成色好一些，上海自提优先。';
const content = '## 综合结论\n\n优先核对候选 #1：卖家描述的 M2 Pro、16GB 内存与 ¥6,800 挂牌价初步符合目标。购买前仍需确认维修记录、电池健康与实物状态。\n\n## 需要继续核实\n\n- 卖家描述尚未独立核验。\n- 请核对屏幕、维修记录和电池循环次数。\n- 本次仅比较 4 件模拟商品，不代表整个市场。';
const cards = [
  ['MacBook Pro 14 · M2 Pro · 16GB / 512GB', 6800, '上海', '卖家描述成色较好'],
  ['MacBook Pro 13 · M2 · 16GB / 512GB', 5600, '杭州', '卖家描述轻微使用痕迹'],
  ['MacBook Pro 14 · M1 Pro · 16GB / 512GB', 4900, '上海', '型号不符合当前目标'],
  ['MacBook Pro 14 · M2 Pro · 16GB / 1TB', 7200, '苏州', '挂牌价超过预算'],
].map(([title, price, city, condition], index) => ({
  listing_id: index + 1, title, url: `https://example.invalid/demo/${index + 1}`,
  price_value: price, price_text: String(price), location: city, seller_name: `模拟卖家 ${index + 1}`,
  search_condition: condition, detail_status: 'captured', research_state: index < 2 ? 'evaluated' : 'waiting',
  source_run_ids: [1], product_images: { state: 'source_missing', source_count: 0, local_count: 0, cover_url: null, cover_media_id: null },
}));
const research = {criteria: [
  {criterion_id: 'model', description: 'M2 或更新芯片', priority: 'hard', source_message_ids: []},
  {criterion_id: 'repair', description: '维修与电池状态', priority: 'soft', source_message_ids: []},
], assessments: [1, 2].map(id => ({listing_id: id, summary: id === 1 ? '配置和报价值得继续核对；维修、电池状态仍需确认。' : '配置描述初步符合；需确认异地交易与实物状态。', conclusion: 'conditional', judgments: [
  {criterion_id: 'model', status: 'MET', reason: '模拟卖家文字描述，尚未独立核验。', source_type: 'seller_claim', evidence_refs: [`claim:${id}`]},
  {criterion_id: 'repair', status: 'UNKNOWN', reason: '缺少维修记录与电池截图。', source_type: 'missing', evidence_refs: []},
]}))};
const project = {
  project: {id: 3, title: '选购二手 MacBook Pro', goal, status: 'active'},
  policy: {budget: 7000, hard: ['MacBook Pro', '芯片至少为 M2', '内存至少 16GB'], soft: ['成色好一些', '上海自提优先'], minimum: 4, paused: 0, auto_research: 1},
  phase: 'incremental', cards, total: 4, eligible: 2, pending: 2, favorites: [1],
  coverage: {evaluated: 2, summarized: 0, waiting: 2, needs_information: 0, under_ai: 0, rule_excluded: 0, blocked: 0},
  goal_context: {current_revision: 1, original_goal: goal, report_current: true, calibration: 'current', legacy_unmerged: false, updated_at: now, automatic_calibration_supported: true},
  report: {id: 1, study_id: 1, goal_revision: 1, evidence_current: true, is_current_goal: true, content, candidate_ids_json: '[1,2]', created_at: now, snapshot_at: now, limited: 1},
  studies: [{id: 1, origin:'automatic_initial', instruction:'按当前目标比较模拟商品的配置、挂牌价和待核实信息。',goal_revision: 1, goal_text: goal, kind: 'initial', state: 'completed', listing_ids: [1,2,3,4], current_listing_ids: [1,2,3,4], created_at: now, snapshot_at: now, finished_at: now, error: null, result: {content:content.replace(/^## 综合结论\n\n/,''), candidate_ids: [1,2], research,check_suggestions:[{listing_id:1,question:'能否提供电池健康、循环次数和维修记录？',reason:'模拟数据中尚缺少相关证据。'}]}}],
  changes: [{id: 1, content: '首份有限样本研究报告已生成，2 件候选值得进一步核对。', created_at: now}],
};
const task = {id: 3, title: project.project.title, goal, status: 'active', created_at: now, updated_at: now, listing_count: 4, run_count: 1};
const tasks = {items: [task], total: 1, truncated: false, page: {has_more: false}};
const monitorBase = {task_id:3, desired_state:null, keyword:'MacBook Pro M2', max_pages:2, max_items:10,
  interval_seconds:1800, collect_seller_profiles:false, imported:4, updated_at:now, error_code:null, result:{}};
const monitors = [
  {...monitorBase,id:1,state:'waiting',rounds:2,max_rounds:1000,next_run_at:'2026-11-01T09:00:00Z'},
  {...monitorBase,id:2,state:'paused',rounds:1,max_rounds:1000,next_run_at:null},
  {...monitorBase,id:3,state:'stopped',rounds:1,max_rounds:1,next_run_at:null},
];
const windows = monitors.map((monitor,index)=>({monitor_id:monitor.id, name:['MacBook Pro · 长期监控','MacBook Pro · 限时监控','MacBook Pro · 单次采集'][index],
  mode:['ongoing','timed','once'][index], duration_seconds:index===1?3600:null, revision:1, monitor,
  runs:[{id:monitor.id,state:index===0?'running':index===1?'paused':'completed',started_at:now,finished_at:index===2?now:null,deadline_at:null,error:null,counts:{records:4,unique_listings:4},config:monitor}]}));
const errors = [], blocked = [], unexpected = new Set();
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  let filename = path.resolve(staticRoot, `.${decodeURIComponent(url.pathname)}`);
  if (!filename.startsWith(staticRoot + path.sep) && filename !== staticRoot) {res.writeHead(403).end(); return;}
  if (!fs.existsSync(filename) || !fs.statSync(filename).isFile()) filename = path.join(staticRoot, 'index.html');
  const mime = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.svg':'image/svg+xml'}[path.extname(filename)] || 'application/octet-stream';
  res.writeHead(200, {'Content-Type': mime}); fs.createReadStream(filename).pipe(res);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1100}, deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block'});
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== base) {blocked.push(url.origin); return route.abort();}
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const p = url.pathname;
    let value;
    if (request.method() === 'POST' && p === '/api/project-goal-drafts') value = {title: task.title, goal: goal.replace('M2', 'M3').replace('7000', '8000'), budget: 8000, hard: ['MacBook Pro', '芯片至少为 M3', '内存至少 16GB'], soft: project.policy.soft, minimum: 4, auto_research: true};
    else if (!['GET','HEAD'].includes(request.method())) {blocked.push(`${request.method()} ${p}`); return route.abort();}
    else if (p === '/api/projects/3/overview') value = project;
    else if (p === '/api/tasks') value = tasks;
    else if (p === '/api/tasks/3') value = {...task, messages: [], runs: [], criteria: [], assessments: [], candidates: []};
    else if (p === '/api/projects/3/monitors') value = {items:windows};
    else if (p === '/api/tasks/3/monitors') value = {items:monitors,enabled:true,platform_enabled:true,candidate_pool_count:4};
    else if (/\/monitors\/\d+\/events$/.test(p)) value = {items:[],has_more:false,next_before_id:null};
    else if (p === '/api/projects/3/investigations') value = {items:[]};
    else if (p === '/api/settings') value = {setup_completed: true, default_city: '上海', platforms: ['xianyu'], allow_ocr: true, preferred_view: 'research'};
    else if (p.includes('setup')) value = {setup_completed:true, environment: [{name:'database', ok:true, detail:'模拟环境检查'}], codex: {cli_available:true, auth_available:true, process_running:false, detail:'模拟状态'}, xianyu:{profile_present:true,auth_status:'verified'}, can_browse_existing_data:true, can_start_research:true};
    else if (p === '/api/health') value = {status:'ok'};
    else if (p === '/api/monitor-engine/check') value = {ready:true,checks:[]};
    else if (p === '/api/projects/3/cover-cache') value = {enabled:false,revision:1,server_enabled:true,counts:{},dropped:0};
    else if (p.includes('browser')) value = {auth_status:'verified', active_job:null};
    else if (p.includes('chat') || p.includes('messages')) value = {items:[], messages:[], session:null, active:null};
    else {unexpected.add(p); value = {items:[]};}
    return route.fulfill({json: value});
  });
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  const stamp = async () => {
    await page.evaluate(() => {
      document.querySelector('#readme-demo-label')?.remove();
      const tag = document.createElement('div'); tag.id = 'readme-demo-label';
      tag.textContent = '界面演示 · 全部数据为模拟';
      tag.style.cssText = 'position:fixed;z-index:9999;top:13px;right:22px;padding:7px 12px;border-radius:7px;background:#eef2ff;color:#4354a3;font:12px system-ui;pointer-events:none';
      document.body.append(tag);
    });
    await page.evaluate(() => document.fonts.ready);
  };
  await page.setViewportSize({width:1440,height:940});
  await page.goto(`${base}/projects/3?view=overview`);
  await page.locator('.sp-overview').waitFor(); await stamp();
  const logo = await page.locator('.sp-brand > span svg').first().evaluate(node => {
    const clone=node.cloneNode(true);clone.setAttribute('x','16');clone.setAttribute('y','16');clone.setAttribute('width','40');clone.setAttribute('height','40');clone.setAttribute('stroke','white');
    return `<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72"><rect width="72" height="72" rx="17" fill="#3b55ff"/>${clone.outerHTML}</svg>`;
  });
  fs.writeFileSync(path.join(output,'readme-logo.svg'),logo);
  await page.screenshot({path: path.join(output, 'readme-overview.png'), animations:'disabled'});
  await page.setViewportSize({width:1440,height:1020});
  await page.goto(`${base}/projects/3?view=products`);
  await page.getByRole('heading', {name:'全部商品', exact:true}).waitFor(); await stamp();
  await page.screenshot({path:path.join(output, 'readme-products.png'), animations:'disabled'});
  for(const [view,name,height] of [['shortlist','shortlist',1120],['monitors','monitors',1250],['research','research',1080]]){
    await page.setViewportSize({width:1440,height});
    await page.goto(`${base}/projects/3?view=${view}`);
    await page.getByRole('heading',{name:{shortlist:'候选清单',monitors:'监控任务',research:'Agent 研究'}[view],exact:true}).waitFor();
    await stamp();await page.screenshot({path:path.join(output,`readme-${name}.png`),animations:'disabled'});
  }
  await page.setViewportSize({width:1440,height:1250});
  await page.goto(`${base}/projects/3?view=overview&editGoal=1`);
  const dialog = page.getByRole('dialog'); await dialog.waitFor();
  await dialog.getByRole('textbox').first().fill('芯片提高到 M3，预算提高到 8000 元，其他要求保留。');
  await dialog.getByRole('button', {name: /整理修改方案/}).click();
  await dialog.getByText('本次拟修改的变化', {exact:true}).waitFor();
  await page.evaluate(() => {const node = document.querySelector('.responsive-drawer__content'); if(node) node.scrollTop = 0;});
  await stamp();
  await page.screenshot({path:path.join(output,'readme-goal-edit.png'), animations:'disabled'});
  if(process.argv.includes('--tour')){
    const directory=path.join(root,'data/artifacts/readme-tour-20261102');fs.mkdirSync(directory,{recursive:true});
    const frames=[];await page.setViewportSize({width:1280,height:900});
    for(const [index,view] of ['overview','shortlist','products','monitors','research'].entries()){
      await page.goto(`${base}/projects/3?view=${view}`);
      await page.locator('.sp-shell').waitFor();
      await page.getByRole('heading',{name:{products:'全部商品',monitors:'监控任务',research:'Agent 研究',shortlist:'候选清单',overview:'研究概览'}[view],exact:true}).waitFor();
      await stamp();const filename=path.join(directory,`frame-${index}.png`);await page.screenshot({path:filename,animations:'disabled'});frames.push(filename);
    }
    const executable=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
    const encoder='import json,sys\nfrom PIL import Image\nframes=[]\nfor path in json.loads(sys.argv[1]):\n with Image.open(path) as frame: frames.append(frame.convert("P",palette=Image.Palette.ADAPTIVE,colors=128))\nframes[0].save(sys.argv[2],save_all=True,append_images=frames[1:],duration=4000,loop=0,optimize=True)';
    const encoded=spawnSync(fs.existsSync(executable)?executable:'python',['-c',encoder,JSON.stringify(frames),path.join(output,'readme-tour.gif')],{windowsHide:true,encoding:'utf8'});
    if(encoded.status!==0)throw Error(`GIF encoding failed: ${encoded.stderr}`);
  }
  if(errors.length || blocked.length) throw new Error(JSON.stringify({errors,blocked}));
  console.log(JSON.stringify({screenshots:6,tour:process.argv.includes('--tour'),externalRequests:0,backendRequests:0,errors,unexpected:[...unexpected]}));
} finally {await browser?.close(); await new Promise(resolve => server.close(resolve));}
