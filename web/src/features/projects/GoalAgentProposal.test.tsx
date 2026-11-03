import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter,useLocation} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it,vi} from 'vitest';
import {GoalAdjustment,GoalContinuityProvider} from './GoalContinuity';
import {projectApi,type ProjectOverview,type ProjectDraft} from '../../api/projectClient';

const data={project:{id:1,title:'手柄项目',goal:'选择手柄'},policy:{budget:400,hard:['NS2 Pro 手柄'],soft:['个人闲置优先'],minimum:20,auto_research:0},goal_context:{current_revision:2,original_goal:'最初选购目标',automatic_calibration_supported:false,legacy_unmerged:false},cards:[],studies:[],favorites:[],report:null} as unknown as ProjectOverview;
const result:ProjectDraft={title:'手柄项目',goal:'预算300元选择 NS2 Pro 手柄，个人闲置优先',budget:300,hard:['NS2 Pro 手柄'],soft:['个人闲置优先'],minimum:20,auto_research:false};
function Location(){const location=useLocation();return <output aria-label="当前路由">{location.pathname+location.search}</output>}
function open(project=data,agent=false){return render(<MemoryRouter initialEntries={['/projects/1?editGoal=1'+(agent?'&goalRequest='+encodeURIComponent('把预算调到300元，其余不变'):'')]}><QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><GoalContinuityProvider data={project}><GoalAdjustment data={project}/><Location/></GoalContinuityProvider></QueryClientProvider></MemoryRouter>)}
function intent(text='把预算调到300元，其余不变'){fireEvent.change(screen.getByLabelText('修改意图'),{target:{value:text}})}
function generate(){fireEvent.click(screen.getByRole('button',{name:'AI 整理修改方案'}))}
function manual(){fireEvent.click(screen.getByRole('button',{name:'直接手动修改'}))}
afterEach(()=>{cleanup();vi.restoreAllMocks()});

it('starts with an intent field and a compact saved goal, without AI or pre-opened editing fields',()=>{
 const draft=vi.spyOn(projectApi,'draft');open();expect(screen.getByLabelText('修改意图')).toHaveValue('');expect(screen.queryByLabelText('调整后的选购目标')).toBeNull();expect(screen.getByRole('button',{name:'预览调整影响'})).toBeDisabled();expect(draft).not.toHaveBeenCalled();expect(screen.getByRole('heading',{name:'当前生效目标 v2'})).toBeVisible();
});
it('separates Agent intent from the complete generated goal and requires impact preview before saving',async()=>{
 const draft=vi.spyOn(projectApi,'draft').mockResolvedValue(result),save=vi.spyOn(projectApi,'saveGoal');open(data,true);
 expect(screen.getByLabelText('修改意图')).toHaveValue('把预算调到300元，其余不变');generate();
 await screen.findByRole('region',{name:'修改草案'});expect(draft).toHaveBeenCalledWith('把预算调到300元，其余不变',{goal:'选择手柄',budget:400,hard:['NS2 Pro 手柄'],soft:['个人闲置优先']});expect(screen.getByText(result.goal)).toBeVisible();fireEvent.click(screen.getByText('其余 2 条条件未变'));expect(screen.getByRole('region',{name:'保留原有条件'})).toHaveTextContent('个人闲置优先');expect(save).not.toHaveBeenCalled();expect(screen.queryByRole('button',{name:'确认并保存修改'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'展开编辑字段'}));expect(screen.getByLabelText('拟定预算上限（元）')).toHaveValue(300);expect(screen.getByLabelText('调整后的选购目标')).toHaveValue(result.goal);
 fireEvent.click(screen.getByRole('button',{name:'预览调整影响'}));expect(screen.getByRole('region',{name:'目标调整影响预览'})).toBeVisible();expect(screen.getByText('展开商品核对详情').closest('details')).not.toHaveAttribute('open');expect(screen.getByText('原报告候选需要怎样复核？')).not.toBeVisible();expect(screen.getByRole('button',{name:'确认并保存修改'})).toBeEnabled();expect(save).not.toHaveBeenCalled();
});
it('preserves intent and the saved baseline after AI failure, with manual editing available',async()=>{
 vi.spyOn(projectApi,'draft').mockRejectedValue(new Error('服务暂不可用'));open();intent();generate();expect(await screen.findByRole('alert')).toHaveTextContent('已保留原表单');expect(screen.getByLabelText('修改意图')).toHaveValue('把预算调到300元，其余不变');manual();expect(screen.getByLabelText('拟定预算上限（元）')).toHaveValue(400);
});
it('replaces stale chip and memory fields, without confusing storage with RAM',async()=>{
 const project={...data,project:{...data.project,title:'MacBook Pro',goal:'MacBook Pro M1'},policy:{...data.policy,hard:['芯片至少为 M1','内存至少32GB']}};
 vi.spyOn(projectApi,'draft').mockResolvedValue({...result,goal:'MacBook Pro M2，存储256GB以上',budget:null,hard:['芯片至少为 M2','存储256GB以上'],soft:[]});open(project);intent('改为 M2，存储256GB以上，取消内存限制');generate();await screen.findByRole('region',{name:'修改草案'});fireEvent.click(screen.getByRole('button',{name:'展开编辑字段'}));expect(screen.getByLabelText('拟定最低内存（GB）')).toHaveValue(null);expect(screen.getByLabelText('保留的硬条件（每行一项）')).toHaveValue('芯片至少为 M2\n存储256GB以上');
});
it('prevents duplicate AI requests and preserves the separate intent',async()=>{
 let resolve!:(value:ProjectDraft)=>void;const draft=vi.spyOn(projectApi,'draft').mockImplementation(()=>new Promise(done=>{resolve=done}));open();intent();const button=screen.getByRole('button',{name:'AI 整理修改方案'});fireEvent.click(button);fireEvent.click(button);expect(draft).toHaveBeenCalledTimes(1);expect(screen.getByLabelText('修改意图')).toBeDisabled();resolve(result);await screen.findByRole('region',{name:'修改草案'});expect(screen.getByLabelText('修改意图')).toBeEnabled();expect(screen.getByLabelText('修改意图')).toHaveValue('把预算调到300元，其余不变');
});
it('invalidates preview and prevents saving an obsolete draft after intent changes',async()=>{
 vi.spyOn(projectApi,'draft').mockResolvedValue(result);open();intent();generate();await screen.findByRole('region',{name:'修改草案'});fireEvent.click(screen.getByRole('button',{name:'预览调整影响'}));intent('预算改成350元');expect(screen.queryByRole('region',{name:'目标调整影响预览'})).toBeNull();expect(screen.getByRole('button',{name:'预览调整影响'})).toBeDisabled();expect(screen.queryByRole('button',{name:'确认并保存修改'})).toBeNull();
});
it('allows manual changes and confirmation without calling AI',async()=>{
 const draft=vi.spyOn(projectApi,'draft'),save=vi.spyOn(projectApi,'saveGoal').mockResolvedValue({revision:3,saved:true});vi.spyOn(projectApi,'monitors').mockResolvedValue({items:[]});open();manual();fireEvent.change(screen.getByLabelText('拟定预算上限（元）'),{target:{value:'500'}});fireEvent.click(screen.getByRole('button',{name:'预览调整影响'}));fireEvent.click(screen.getByRole('button',{name:'确认并保存修改'}));await screen.findByText('已从 v2 更新为 v3');expect(draft).not.toHaveBeenCalled();expect(save).toHaveBeenCalledWith(1,{goal:'选择手柄',budget:500,hard:['NS2 Pro 手柄'],soft:['个人闲置优先']},2,expect.any(String));
});
it('updates a manual minimum memory without retaining the previous contradictory hard condition',async()=>{
 const project={...data,project:{...data.project,title:'MacBook Pro',goal:'MacBook Pro M2'},policy:{...data.policy,hard:['内存至少32GB']}};const save=vi.spyOn(projectApi,'saveGoal').mockRejectedValue(new Error('test stop'));open(project);manual();fireEvent.change(screen.getByLabelText('拟定最低内存（GB）'),{target:{value:'16'}});fireEvent.click(screen.getByRole('button',{name:'预览调整影响'}));fireEvent.click(screen.getByRole('button',{name:'确认并保存修改'}));await screen.findByRole('alert');expect(save.mock.calls[0][1].hard).toEqual(['内存至少16GB']);
});
it('keeps the saved current version fixed while preparing a new draft',()=>{
 const project={...data,project:{...data.project,goal:'当前已保存 M2'},goal_context:{...data.goal_context!,original_goal:'最初目标 M1'}};open(project);const before=screen.getByRole('region',{name:'修改前的已保存目标'});manual();fireEvent.change(screen.getByLabelText('调整后的选购目标'),{target:{value:'准备调整为 M3'}});expect(before).toHaveTextContent('当前生效目标 v2');expect(before).toHaveTextContent('当前已保存 M2');expect(before).not.toHaveTextContent('最初目标 M1');expect(before).not.toHaveTextContent('准备调整为 M3');
});
it('confirms before abandoning intent for the existing project creation flow',()=>{
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);open();intent('改买相机');fireEvent.click(screen.getByRole('button',{name:'新建选购项目 →'}));expect(confirm).toHaveBeenCalledWith(expect.stringContaining('放弃'));expect(screen.getByLabelText('修改意图')).toHaveValue('改买相机');confirm.mockReturnValue(true);fireEvent.click(screen.getByRole('button',{name:'新建选购项目 →'}));expect(screen.queryByRole('dialog')).toBeNull();expect(screen.getByLabelText('当前路由')).toHaveTextContent('create=1');expect(screen.getByLabelText('当前路由')).not.toHaveTextContent('editGoal');
});
it('offers project creation without confirmation when no draft has been entered',()=>{
 const confirm=vi.spyOn(window,'confirm');open();fireEvent.click(screen.getByRole('button',{name:'新建选购项目 →'}));expect(confirm).not.toHaveBeenCalled();expect(screen.getByLabelText('当前路由')).toHaveTextContent('create=1');
});
