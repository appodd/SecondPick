import {expect,test} from '@playwright/test';
import {syntheticMarket} from './synthetic-market';

for(const model of ['Synthetic Camera Z9','Synthetic SSD Q2','Synthetic Chair V3','Previously Unseen Widget','Unknown'])test(`generic saved-attribute market: ${model}`,async({page})=>{
  await syntheticMarket(page,model,model==='Unknown');
  const writes:string[]=[];page.on('request',r=>{if(r.method()!=='GET')writes.push(r.url())});
  await page.goto('/projects/10?view=products&display=market&marketFor=101');
  await expect(page.getByText(/统一口径：明确商品身份与保存属性分层/)).toBeVisible();
  const reference=page.getByLabel('商品 101 挂牌参考');await expect(reference).toContainText('¥100.5');
  if(model==='Unknown'){
    await expect(reference.getByRole('status')).toContainText('所售型号未明确');
    await expect(page.locator('.sp-market-bin')).toHaveCount(0);
  }else{
    await expect(reference).toContainText('严格对照 1 件');
    await expect(page.getByRole('heading',{name:'比较样本 · 1 件',exact:true})).toBeVisible();
    await expect(page.locator('.sp-market-samples')).toContainText('#102');
    await page.getByLabel('行情比较层级').selectOption('broad');
    await expect(page.getByRole('heading',{name:'比较样本 · 2 件',exact:true})).toBeVisible();
    await page.goto('/projects/10?view=products&display=market');
    await expect(page.getByLabel('可比商品分组')).toContainText(model);
  }
  expect(writes).toEqual([]);
});
