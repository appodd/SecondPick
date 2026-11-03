import {cleanup,render,screen,within} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {GoalChanges} from './GoalChanges';
afterEach(cleanup);
const before={goal:'MacBook Pro M1',budget:5000,hard:['芯片至少为 M1'],soft:['上海优先']};
it('shows old and proposed conditions, including removals and an unset budget',()=>{
 render(<GoalChanges before={before} after={{goal:'MacBook Pro M2',budget:null,hard:['芯片至少为 M2','原装无拆修'],soft:[]}}/>);
 expect(screen.getByRole('heading',{name:'本次拟修改的变化'})).toBeVisible();
 const rows=screen.getAllByRole('row');expect(rows).toHaveLength(4);
 expect(within(rows[1]).getAllByRole('cell').map(e=>e.textContent)).toEqual(['¥5,000','未设置']);
 expect(within(rows[2]).getAllByRole('cell').map(e=>e.textContent)).toEqual(['芯片至少为 M1','芯片至少为 M2原装无拆修']);
 expect(within(rows[3]).getAllByRole('cell').map(e=>e.textContent)).toEqual(['上海优先','无新增项']);
});
it('does not report reordered conditions as new requirements',()=>{render(<GoalChanges before={{...before,hard:['A','B']}} after={{...before,hard:['B','A','A']}}/>);expect(screen.queryByRole('table')).toBeNull();expect(screen.getByText('尚未调整已保存的目标与条件。')).toBeVisible()});
it('explains that editing the description alone has not updated structured conditions',()=>{render(<GoalChanges before={before} after={{...before,goal:'MacBook Pro M2'}}/>);expect(screen.getByText(/预算、必须条件和偏好尚无变化/)).toBeVisible()});
it('shows only changed entries and collapses unchanged conditions by default',()=>{
 render(<GoalChanges before={{...before,hard:['M2','原装无拆修']}} after={{...before,hard:['M3','原装无拆修','16GB']}} showRetained/>);
 const counts=screen.getByLabelText('条件条目变化统计');expect(counts).toHaveTextContent('新增 2 条');expect(counts).toHaveTextContent('移除 1 条');expect(screen.getByRole('table')).not.toHaveTextContent('原装无拆修');
 const summary=screen.getByText('其余 2 条条件未变');expect(summary.closest('details')).not.toHaveAttribute('open');expect(screen.getByText('原装无拆修')).not.toBeVisible();summary.click();
 const retained=screen.getByRole('region',{name:'保留原有条件'});expect(retained).toHaveTextContent('原装无拆修');expect(retained).toHaveTextContent('上海优先');expect(retained).not.toHaveTextContent('M3');
});
it('reports only the new black preference when chip and capacity requirements are unchanged',()=>{
 const original={...before,goal:'MacBook Pro M3',hard:['MacBook Pro','芯片至少为 M3','硬盘存储容量256GB以上','原装无拆修'],soft:['成色好一些','上海自提优先']};
 render(<GoalChanges before={original} after={{...original,hard:['MacBook Pro','芯片至少为 M3','硬盘存储容量256G以上','原装无拆修'],soft:[...original.soft,'黑色']}} showRetained/>);
 const table=screen.getByRole('table');expect(table).not.toHaveTextContent('必须条件');expect(table).toHaveTextContent('个人偏好');expect(table).toHaveTextContent('黑色');expect(screen.getByLabelText('条件条目变化统计')).toHaveTextContent('新增 1 条');expect(screen.getByLabelText('条件条目变化统计')).not.toHaveTextContent('移除');expect(screen.getByText('其余 6 条条件未变')).toBeVisible();
});
