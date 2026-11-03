import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const root=path.resolve(process.cwd(),process.cwd().endsWith('web')?'..':'.');
const artifacts=process.env.SECONDPICK_P3_FIXTURE_DIR ?? path.join(root,'data/artifacts/p3-market-20261024');
const snapshots=JSON.parse(fs.readFileSync(path.join(artifacts,'before-overviews.json'),'utf8'));
const evidence=JSON.parse(fs.readFileSync(path.join(artifacts,'evidence-1879.json'),'utf8'));

test('P3 saved real cohort, layers, traceable samples and drawer without live actions',async({page},info)=>{
  let writes=0;
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.hostname!=='127.0.0.1' && url.hostname!=='localhost')return route.abort();
    if(request.method()!=='GET'){writes++;return route.abort();}
    if(url.pathname==='/api/projects/3/overview'){
      const view=structuredClone(snapshots['3']);view.cards.forEach((c:{image_url?:string|null})=>c.image_url=null);
      return route.fulfill({json:view});
    }
    if(url.pathname==='/api/listings/1879/evidence')return route.fulfill({json:evidence});
    if(/\/api\/tasks\/3\/listings\/\d+\/images/.test(url.pathname))return route.fulfill({json:{listing_id:1879,images:[]}});
    if(url.pathname==='/api/projects/3/investigations')return route.fulfill({json:{items:[],limit:3}});
    return route.continue();
  });
  const ref=snapshots['3'].market.references['1879'];
  await page.goto('/projects/3?view=products&display=market&marketFor=1879');
  await expect(page.getByLabel('商品 1879 挂牌参考')).toContainText('¥328');
  await expect(page.getByRole('heading',{name:`比较样本 · ${ref.strict.count} 件`,exact:true})).toBeVisible();
  await expect(page.getByText(/样本少，不展示精确排名或价格评分/)).toBeVisible();
  await page.getByLabel('行情比较层级').selectOption('broad');
  await expect(page.getByRole('heading',{name:`比较样本 · ${ref.broad.count} 件`,exact:true})).toBeVisible();
  await expect(page.locator('.sp-market-samples > button')).toHaveCount(ref.broad.count);
  expect(await page.locator('.sp-market-samples').innerText()).not.toContain('#1879');
  await page.locator('.sp-market-bin').first().click();
  await page.getByRole('button',{name:'显示本层全部样本',exact:true}).click();
  await expect(page.locator('.sp-market-marker line')).toHaveCount(1);
  await page.getByText('样本条件、来源与限制',{exact:true}).click();
  await expect(page.getByText(/不是成交行情/)).toBeVisible();
  await page.screenshot({path:info.outputPath('p3-market.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.goto('/projects/3?view=products&listing=1879');
  // Open from the real product table, retaining the common evidence drawer.
  await page.getByPlaceholder(/搜索/).first().fill('switch2 pro原装正品');
  await page.locator('button.sp-product-cell').first().click();
  const drawer=page.getByRole('dialog',{name:'商品与卖家证据'});
  await expect(drawer.getByLabel('商品 1879 挂牌参考')).toContainText('¥328');
  await expect(drawer.getByRole('region',{name:'新证据与有限复评'})).toContainText('研究已暂停；保留新证据，不启动模型');
  await drawer.getByLabel('商品 1879 挂牌参考').scrollIntoViewIfNeeded();
  await page.screenshot({path:info.outputPath('p3-detail.png')});
  expect(writes).toBe(0);
});

test('P3 real MacBook groups never merge Intel M1 M2; unknown is not a cohort',async({page},info)=>{
  await page.route('**/api/projects/1/overview',route=>route.fulfill({json:snapshots['1']}));
  await page.route('https://**/*',route=>route.abort());
  await page.goto('/projects/1?view=products&display=market');
  const select=page.getByLabel('可比商品分组');await expect(select).toBeVisible();
  const options=await select.locator('option').allTextContents();
  for(const option of options)expect((option.match(/Intel|M1|M2/g)??[]).length).toBeLessThanOrEqual(1);
  expect(options.some(o=>o.includes('M1'))).toBe(true);
  expect(options.some(o=>o.includes('M2'))).toBe(true);
  expect(options.some(o=>o.includes('未识别'))).toBe(false);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:info.outputPath('p3-macbook.png'),fullPage:true});
});

test('P3 overview and candidate comparison share saved local baselines without updating AI conclusions',async({page},info)=>{
  let writes=0;
  const view=structuredClone(snapshots['3']);view.cards.forEach((c:{image_url?:string|null})=>c.image_url=null);
  const ids:number[]=JSON.parse(view.report.candidate_ids_json).slice(0,2);
  await page.route('**/*',route=>{
    const r=route.request(),url=new URL(r.url());
    if(!['127.0.0.1','localhost'].includes(url.hostname))return route.abort();
    if(r.method()!=='GET'){writes++;return route.abort();}
    if(url.pathname==='/api/projects/3/overview')return route.fulfill({json:view});
    return route.continue();
  });
  await page.goto('/projects/3?view=overview');
  await expect(page.getByLabel(`商品 ${ids[0]} 挂牌参考`)).toBeVisible();
  await page.goto(`/projects/3?view=shortlist&compare=${ids.join(',')}`);
  await expect(page.getByRole('heading',{name:'候选比较 · 2 件',exact:true})).toBeVisible();
  for(const id of ids){
    const ref=view.market.references[id];
    await expect(page.getByLabel(`商品 ${id} 挂牌参考`)).toContainText(`宽泛参考 ${ref.broad.count} 件`);
  }
  expect(writes).toBe(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:info.outputPath('p3-comparison.png'),fullPage:true});
});
