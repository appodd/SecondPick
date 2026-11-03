import {expect,test} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const root=path.resolve(process.cwd(),process.cwd().endsWith('web')?'..':'.');
const cases=JSON.parse(fs.readFileSync(path.join(root,'data/artifacts/p3-generic-fix-20261024/generic-fixtures.json'),'utf8'));

for(const name of ['camera','ssd','chair','unseen_fixture','no_identity'])test(`generic saved-attribute market: ${name}`,async({page},info)=>{
  const data=cases[name].overview;
  let writes=0;
  await page.route('**/*',route=>{
    const req=route.request(),url=new URL(req.url());
    if(!['127.0.0.1','localhost'].includes(url.hostname))return route.abort();
    if(req.method()!=='GET'){writes++;return route.abort();}
    if(url.pathname==='/api/projects/3/overview')return route.fulfill({json:data});
    return route.continue();
  });
  await page.goto('/projects/3?view=products&display=market&marketFor=101');
  await expect(page.getByText(/统一口径：明确商品身份与保存属性分层/)).toBeVisible();
  const ref=data.market.references['101'];
  const stats=page.getByLabel('商品 101 挂牌参考');
  await expect(stats).toContainText('¥100.5');
  if(name==='no_identity'){
    await expect(stats.getByRole('status')).toContainText('所售型号未明确');
    await expect(page.locator('.sp-market-bin')).toHaveCount(0);
    await expect(page.getByText(/不静默回退到旧混合统计/)).toBeVisible();
  }else{
    await expect(stats).toContainText('严格对照 1 件');
    await expect(page.getByRole('heading',{name:'比较样本 · 1 件',exact:true})).toBeVisible();
    await expect(page.locator('.sp-market-samples > button')).toHaveCount(1);
    await expect(page.locator('.sp-market-samples')).toContainText('#102');
    expect(ref.strict.member_ids).toEqual([102]);
    await page.getByLabel('行情比较层级').selectOption('broad');
    await expect(page.getByRole('heading',{name:'比较样本 · 1 件',exact:true})).toBeVisible();
    await page.goto('/projects/3?view=products&display=market');
    await expect(page.getByLabel('可比商品分组')).toBeVisible();
    await expect(page.getByLabel('可比商品分组')).toContainText(data.market.references['101'].model);
    await expect(page.getByText('按当前明确属性分组，未知属性不等于严格相同',{exact:true})).toBeVisible();
  }
  expect(writes).toBe(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:info.outputPath(`generic-${name}.png`),fullPage:true});
});
