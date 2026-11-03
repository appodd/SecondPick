import { cleanup,render,screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach,expect,it } from 'vitest';
import type { ProjectOverview } from '../../api/projectClient';
import { EvidenceChanges } from './EvidenceChanges';
afterEach(cleanup);
function data(state='priority') {
  return { evidence_work:{gate:'paused',reason:'研究已暂停；保留新证据，不启动模型',batch_limit:3,listing_ids:[1879],items:[{listing_id:1879,state,reason:'商品属性与完整描述变化',study_id:null,previous:{study_id:50,assessment:{summary:'原来缺少详情',conclusion:'insufficient_evidence'}},delta:{fields:['attributes'],before:{attributes:{}},after:{attributes:{型号:'NS2 Pro'}}}}]},
    integration_work:{state:'none',reason:'无重大判断变化',listing_ids:[]}, report:{evidence_current:false} } as unknown as ProjectOverview;
}
it('shows paused decision, previous judgment and delta without research action',async()=>{
 render(<EvidenceChanges data={data()}/>);
 expect(screen.getByText(/研究已暂停/)).toBeVisible();
 expect(screen.getByText(/旧建议当作最新判断/)).toBeVisible();
 await userEvent.click(screen.getByText('查看变化、旧判断与复评原因'));
 expect(screen.getByText(/#1879 · 值得优先复评/)).toBeVisible();
 expect(screen.getByText(/原来缺少详情/)).toBeVisible();
 expect(screen.queryByRole('button')).toBeNull();
});
it('distinguishes failed attempt and URLs from visual verification',async()=>{
 render(<EvidenceChanges data={data('failed')}/>);
 await userEvent.click(screen.getByText('查看变化、旧判断与复评原因'));
 expect(screen.getByText(/#1879 · 复评失败/)).toBeVisible();
 expect(screen.getByText(/图片已保存不代表 AI 已看图/)).toBeVisible();
});
it('scopes listing details and shows completed result separately',()=>{
 const value=data();value.evidence_work!.items=[];
 value.integration_work!.updates=[{item:{listing_id:1879},study_id:53,assessment:{summary:'新证据仍不能核实维修'}}];
 render(<EvidenceChanges data={value} listing={1879}/>);
 expect(screen.getByText('查看已完成的新判断（保留历史）')).toBeVisible();
});
