import {expect,test} from '@playwright/test';
import {syntheticMarket} from './synthetic-market';

test('saved cohort layers retain traceable peers, exclude target and perform no writes',async({page})=>{
  await syntheticMarket(page);const writes:string[]=[];page.on('request',r=>{if(r.method()!=='GET')writes.push(r.url())});
  await page.goto('/projects/10?view=products&display=market&marketFor=101');
  await expect(page.getByLabel('商品 101 挂牌参考')).toContainText('¥100.5');
  await expect(page.getByRole('heading',{name:'比较样本 · 1 件',exact:true})).toBeVisible();
  await page.getByLabel('行情比较层级').selectOption('broad');
  await expect(page.locator('.sp-market-samples > button')).toHaveCount(2);
  await expect(page.locator('.sp-market-samples')).not.toContainText('#101');
  await page.locator('.sp-market-bin').first().click();await page.getByRole('button',{name:'显示本层全部样本',exact:true}).click();
  await expect(page.locator('.sp-market-marker line')).toHaveCount(1);
  await page.getByText('样本条件、来源与限制',{exact:true}).click();await expect(page.getByText(/挂牌不是成交价/)).toBeVisible();
  expect(writes).toEqual([]);
});
test('explicit Intel M1 M2 groups stay separate and unknown identity is not a cohort',async({page})=>{
  const data=await syntheticMarket(page,'MacBook Pro');
  data.market.groups=['Intel','M1','M2'].map((chip,i)=>({key:chip,label:`MacBook Pro ${chip}`,model:`MacBook Pro ${chip}`,member_ids:[101+i],summary:{count:1,median:100+i}}));
  await page.goto('/projects/10?view=products&display=market');
  const options=await page.getByLabel('可比商品分组').locator('option').allTextContents();
  for(const chip of ['Intel','M1','M2'])expect(options.some(o=>o.includes(chip))).toBe(true);
  for(const option of options)expect((option.match(/Intel|M1|M2/g)??[]).length).toBeLessThanOrEqual(1);
});
test('evidence drawer shares saved baseline without rewriting research',async({page})=>{
  await syntheticMarket(page);const writes:string[]=[];page.on('request',r=>{if(r.method()!=='GET')writes.push(r.url())});
  await page.goto('/projects/10?view=products&q=sample%201');await page.locator('button.sp-product-cell').first().click();
  const drawer=page.getByRole('dialog',{name:'商品与卖家证据'});
  await expect(drawer.getByLabel('商品 101 挂牌参考')).toContainText('宽泛参考 2 件');
  await drawer.getByRole('button',{name:'查看行情参考',exact:true}).click();
  await expect(page.getByRole('heading',{name:/市场行情参考/})).toBeVisible();expect(writes).toEqual([]);
});
