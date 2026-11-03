import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {shoppingFixture} from '../../test/shoppingFixture';
import {Research} from './Research';
import {GoalContinuityProvider} from './GoalContinuity';
const open=vi.hoisted(()=>vi.fn());
vi.mock('./ProjectAgent',()=>({useProjectAgent:()=>({open})}));
vi.mock('./Investigations',()=>({Investigations:()=>null}));
vi.mock('./ReportHistory',()=>({ReportHistory:()=>null}));
vi.mock('../inspector/VisualEvidence',()=>({VisualEvidence:()=>null}));
const originalScroll = HTMLElement.prototype.scrollIntoView;
beforeEach(()=>{HTMLElement.prototype.scrollIntoView=vi.fn()});
afterEach(()=>{cleanup();open.mockClear();HTMLElement.prototype.scrollIntoView=originalScroll});
function mount(){const d=shoppingFixture();d.studies[0].origin='confirmed_snapshot';const action=vi.fn();render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><GoalContinuityProvider data={d}><Research data={d} action={action} busy={false}/></GoalContinuityProvider></MemoryRouter></QueryClientProvider>);return {d,action}}
it('continues a result through the shared Agent with an actual study binding',()=>{const {action}=mount();fireEvent.click(screen.getByRole('button',{name:'继续追问'}));expect(open).toHaveBeenCalledWith(expect.objectContaining({studyId:1,ids:[1,2],role:'interpret'}));expect(action).not.toHaveBeenCalled()});
it('deeper investigation prepares a bounded Agent draft without executing a task',()=>{const {action}=mount();fireEvent.click(screen.getByRole('button',{name:'深入调查'}));expect(open).toHaveBeenCalledWith(expect.objectContaining({ids:[3,4,5],question:expect.stringContaining('深入调查')}));expect(action).not.toHaveBeenCalled();expect(screen.queryByRole('button',{name:'本次研究重点'})).toBeNull()});
it('keeps task evidence collapsed and pause state visible without hiding scheduling controls',()=>{mount();const detail=screen.getByText('任务详情与证据').closest('details')!;expect(detail).not.toHaveAttribute('open');for(const text of within(detail).getAllByText(/固定快照/))expect(text).not.toBeVisible();expect(screen.getByRole('status')).toHaveTextContent('研究调度已暂停');expect(screen.getByRole('button',{name:'研究下一个有限批次'})).toBeDisabled();expect(screen.getByRole('button',{name:'恢复研究调度'})).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'查看研究覆盖'}));expect(document.querySelector('.ua-research-scheduling')).toHaveAttribute('open')});
