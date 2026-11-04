import {expect,test} from '@playwright/test';
import {createHash} from 'node:crypto';
import {syntheticMarket} from './synthetic-market';

// The old attachment-proof panel was replaced by VisualEvidence. Test the
// current binding checks with synthetic pixels and observations, never a model.
for(const invalid of ['none','listing','hash','text-only','no-image-input','mock'])test(`visual provenance: ${invalid}`,async({page})=>{
  await syntheticMarket(page);
  const pixels='<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="blue"/></svg>';
  const hash=createHash('sha256').update(pixels).digest('hex'),writes:string[]=[];
  const image={media_id:1,sha256:hash,width:2,height:2,source_url:'https://example.test/synthetic.png'};
  const observation={id:'visual:101:987:synthetic',listing_id:invalid==='listing'?999:101,study_id:987,run_id:'123',media_id:1,
    sha256:invalid==='hash'?'b'.repeat(64):hash,visible_content:'SYNTHETIC OBSERVATION',limited_inference:'',uncertainty:'Synthetic pixels cannot prove real condition',
    status:'visible',origin:invalid==='text-only'?'text':'pixels',source_type:'image_observation',provider:'offline',model:'synthetic',review_state:'accepted',independently_verified:false,mode:'mock',references:[]};
  await page.route('**/api/projects/10/listings/101/visual-evidence',route=>route.fulfill({json:{task_id:10,listing_id:101,goal_revision:1,state:'idle',approval_allowed:false,approval_blocked_reason:'Offline only',execution_enabled:false,
    images:invalid==='no-image-input'?[]:[image],observations:invalid==='none'?[]:[observation],rejected_observations:0,unavailable_images:0,failures:[]}}));
  await page.route('**/visual-images/1?*',route=>route.fulfill({contentType:'image/svg+xml',body:pixels}));
  page.on('request',r=>{if(r.method()!=='GET')writes.push(r.url())});
  await page.goto('/projects/10?view=products&q=sample%201');await page.locator('button.sp-product-cell').first().click();
  const proof=page.getByRole('region',{name:'图片观察与审批'});
  await expect(proof).toContainText('AI 看图不等于实物已核验');
  if(invalid==='mock'){
    await expect(proof).toContainText('离线 Mock');await expect(proof).toContainText('非独立核验');
    await expect(proof.getByRole('img')).toHaveAttribute('src',new RegExp(`sha256=${hash}`));
  }else{
    await expect(proof).toContainText('暂无有效 AI 图片观察');
    await expect(proof).not.toContainText('SYNTHETIC OBSERVATION');
  }
  expect(writes).toEqual([]);
});
