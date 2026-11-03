import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,fireEvent} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ProjectGoalCard} from './ProjectGoalCard';
import {GoalMonitorReview} from './GoalMonitorReview';
import {projectApi} from '../../api/projectClient';
import {shoppingFixture} from '../../test/shoppingFixture';
afterEach(()=>{cleanup();vi.restoreAllMocks()});
function wrap(child:React.ReactNode){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter>{child}</MemoryRouter></QueryClientProvider>)}
it('shows current conditions and a versioned edit entry without running AI',async()=>{
 const data=shoppingFixture();data.project.goal='MacBook Pro M2';data.policy.hard=['32GB'];
 const history=vi.spyOn(projectApi,'goalHistory').mockResolvedValue({items:[{revision:1,goal:'MacBook Pro M1',budget:5000,hard:[],soft:[],created_at:'2026-10-29T00:00:00Z'}],has_more:false});
 wrap(<ProjectGoalCard data={data}/>);expect(screen.getByText('MacBook Pro M2')).toBeVisible();expect(screen.getByRole('link',{name:'调整目标 →'})).toHaveAttribute('href',expect.stringContaining('editGoal=1'));expect(history).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'查看历史目标'}));expect(await screen.findByText('MacBook Pro M1')).toBeVisible();
});
it('prepares a missing scope through the existing creator without starting collection',async()=>{
 vi.spyOn(projectApi,'monitors').mockResolvedValue({items:[]});const create=vi.spyOn(projectApi,'createMonitor');
 wrap(<GoalMonitorReview id={1} goal="MacBook Pro M2" hard={[]}/>);
 const link=await screen.findByRole('link',{name:'准备创建 M2 监控 →'});expect(new URL(link.getAttribute('href')!,'http://localhost').searchParams.get('draftKeyword')).toBe('MacBook Pro M2');expect(create).not.toHaveBeenCalled();
});
it('does not interpret a failed monitor read as a missing scope',async()=>{
 vi.spyOn(projectApi,'monitors').mockRejectedValue(new Error('offline'));wrap(<GoalMonitorReview id={1} goal="MacBook Pro M2" hard={[]}/>);expect(await screen.findByRole('alert')).toHaveTextContent('不将读取失败视为缺少监控');expect(screen.queryByRole('link',{name:'准备创建 M2 监控 →'})).toBeNull();
});
