import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it,vi} from 'vitest';
import {ProjectAgentProvider,SharedAgentPanel,useProjectAgent} from './ProjectAgent';
import {projectApi,type ProjectOverview} from '../../api/projectClient';
import {request} from '../../api/client';
vi.mock('../../api/client',()=>({request:vi.fn()}));
vi.mock('./GoalContinuity',()=>({useGoalContinuity:()=>({state:'unversioned'})}));
const data={project:{id:1,title:'试验项目',goal:'选择手柄'},cards:[{listing_id:1,title:'手柄1'}],studies:[],favorites:[],goal_context:{current_revision:2},policy:{paused:0,completed:0},coverage:{}} as unknown as ProjectOverview;
function Launcher(){const a=useProjectAgent();return <><button onClick={()=>a.open({role:'interpret',ids:[1],label:'选择的商品'})}>打开 Agent</button><SharedAgentPanel select={()=>{}}/></>}
function open(paused=false){vi.mocked(request).mockResolvedValue({items:[]});render(<MemoryRouter><QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ProjectAgentProvider data={{...data,policy:{...data.policy,paused:paused?1:0}}} view="overview"><Launcher/></ProjectAgentProvider></QueryClientProvider></MemoryRouter>);fireEvent.click(screen.getByRole('button',{name:'打开 Agent'}))}
afterEach(()=>{cleanup();vi.restoreAllMocks()});
it('ordinary question uses conversation API, never the studies API',async()=>{const study=vi.spyOn(projectApi,'study');open();fireEvent.change(screen.getByLabelText('给 Agent 的指令'),{target:{value:'为什么推荐？'}});fireEvent.click(screen.getByRole('button',{name:'发送'}));await waitFor(()=>expect(vi.mocked(request).mock.calls.some(c=>String(c[0]).endsWith('/agent-chat')&&c[1]?.method==='POST')).toBe(true));expect(study).not.toHaveBeenCalled()});
it('a formal study requires a separate explicit confirmation',async()=>{const study=vi.spyOn(projectApi,'study').mockResolvedValue({id:7});open();fireEvent.change(screen.getByLabelText('给 Agent 的指令'),{target:{value:'深入调查这件商品'}});fireEvent.click(screen.getByRole('button',{name:'发送'}));expect(study).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'确认并创建研究任务'}));await waitFor(()=>expect(study).toHaveBeenCalledTimes(1))});
it('pause blocks research confirmation without blocking ordinary Q&A',()=>{open(true);fireEvent.change(screen.getByLabelText('\u7ed9 Agent \u7684\u6307\u4ee4'),{target:{value:'\u666e\u901a\u95ee\u9898'}});expect(screen.getByRole('button',{name:'\u53d1\u9001'})).not.toBeDisabled();fireEvent.change(screen.getByLabelText('\u7ed9 Agent \u7684\u6307\u4ee4'),{target:{value:'\u6df1\u5165\u8c03\u67e5\u8fd9\u4ef6\u5546\u54c1'}});fireEvent.click(screen.getByRole('button',{name:'\u53d1\u9001'}));expect(screen.getByRole('button',{name:'\u786e\u8ba4\u5e76\u521b\u5efa\u7814\u7a76\u4efb\u52a1'})).toBeDisabled()});
it('a natural-language configuration request only opens a plan choice',()=>{const study=vi.spyOn(projectApi,'study');open();fireEvent.change(screen.getByLabelText('给 Agent 的指令'),{target:{value:'把监控改为30分钟'}});fireEvent.click(screen.getByRole('button',{name:'发送'}));expect(screen.getByLabelText('调整哪项监控')).toBeVisible();expect(study).not.toHaveBeenCalled();expect(vi.mocked(request).mock.calls.every(c=>c[1]?.method!=='POST')).toBe(true)});
