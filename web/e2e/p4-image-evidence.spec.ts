import {expect,test} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(process.cwd(),process.cwd().endsWith('web')?'..':'.');
const snapshots=JSON.parse(fs.readFileSync(path.join(root,'data/artifacts/p3-wording-formal-load-20261025/live-overviews.json'),'utf8'));
const evidence=JSON.parse(fs.readFileSync(path.join(root,'data/artifacts/p3-generic-fix-20261024/evidence-1879.json'),'utf8'));
test('P4 synthetic proof states in existing drawer never claim real vision',async({page},info)=>{
 let writes=0;
 await page.route('**/*',route=>{
  const r=route.request(),u=new URL(r.url());
  if(!['127.0.0.1','localhost'].includes(u.hostname))return route.abort();
  if(r.method()!=='GET'){writes++;return route.abort();}
  if(u.pathname==='/api/projects/3/overview')return route.fulfill({json:snapshots['3']});
  if(u.pathname==='/api/listings/1879/evidence')return route.fulfill({json:evidence});
  if(u.pathname==='/api/tasks/3/listings/1879/images')return route.fulfill({json:{listing_id:1879,images:[
   {id:1,url:'https://img.alicdn.com/offline-fixture-1.png',created_at:'2026-10-25',evidence:{state:'url_only',observed:false}},
   {id:2,url:'https://img.alicdn.com/offline-fixture-2.png',created_at:'2026-10-25',evidence:{state:'saved',observed:false}},
   {id:3,url:'https://img.alicdn.com/offline-fixture-3.png',created_at:'2026-10-25',evidence:{state:'saved',observed:false,input_uses:[{study_id:987,goal_revision:1,input_constructed:true,remote_received:false,observed:false}]}}
  ]}});
  return route.continue();
 });
 await page.goto('/projects/3?view=products');await page.getByPlaceholder(/搜索/).first().fill('switch2 pro原装正品');
 await page.locator('button.sp-product-cell').first().click();
 const drawer=page.getByRole('dialog',{name:'商品与卖家证据'});
 const proof=drawer.getByLabel('图片证据状态');await proof.getByText('图片证据与模型使用',{exact:true}).click();
 await expect(proof.getByText(/图片 1：/)).toContainText('尚未保存文件');
 await expect(proof.getByText(/图片 2：/)).toContainText('图片文件已保存并校验');
 await expect(proof.getByText(/图片 3：/)).toContainText('附件已构造');
 await expect(proof.getByText(/图片 3：/)).toContainText('尚未确认送达模型');
 await expect(proof.getByText(/视觉观察：/)).toContainText('尚无已验证的真实记录');
 await proof.scrollIntoViewIfNeeded();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:info.outputPath('p4-image-proof.png')});expect(writes).toBe(0);
});
