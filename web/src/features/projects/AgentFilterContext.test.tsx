import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter,useSearchParams} from 'react-router-dom';
import {afterEach,expect,it,vi} from 'vitest';
import {shoppingFixture} from '../../test/shoppingFixture';
import {ProjectAgentProvider,SharedAgentPanel,useProjectAgent} from './ProjectAgent';
import {request} from '../../api/client';
vi.mock('../../api/client',()=>({request:vi.fn()}));
vi.mock('./GoalContinuity',()=>({useGoalContinuity:()=>({state:'unversioned'})}));
afterEach(()=>{cleanup();vi.clearAllMocks()});
function Shell(){const [params,set]=useSearchParams();return <ProjectAgentProvider data={shoppingFixture()} view="products"><button onClick={()=>set({q:'不存在'})}>无结果</button><button onClick={()=>set({})}>清除筛选</button><Entry/></ProjectAgentProvider>}
function Entry(){const a=useProjectAgent();return <><button onClick={()=>a.open()}>打开</button><SharedAgentPanel select={()=>{}}/></>}
function mount(){vi.mocked(request).mockResolvedValue({items:[]});render(<MemoryRouter initialEntries={['/projects/3?view=products&q=%232']}><QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><Shell/></QueryClientProvider></MemoryRouter>);fireEvent.click(screen.getByRole('button',{name:'打开'}))}
it('the single Agent automatically uses the bounded current filter without submitting',async()=>{mount();await screen.findByText(/当前筛选结果前1件，共1件/);expect(screen.getByRole('complementary')).toHaveTextContent('本次关联 1 件商品');expect(screen.getByRole('complementary').querySelector('.ua-products')).toHaveTextContent('#2');expect(vi.mocked(request).mock.calls.every(c=>c[1]?.method!=='POST')).toBe(true)});
it('zero results cannot silently become a whole-project request and clearing restores project scope',async()=>{mount();await screen.findByText(/当前筛选结果前1件，共1件/);fireEvent.click(screen.getByRole('button',{name:'无结果'}));await screen.findByText(/当前筛选没有商品/);fireEvent.change(screen.getByLabelText('给 Agent 的指令'),{target:{value:'比较这些商品'}});expect(screen.getByRole('button',{name:'发送'})).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'清除筛选'}));await waitFor(()=>expect(screen.getByRole('complementary')).toHaveTextContent('围绕整个选购项目'));expect(screen.getByRole('button',{name:'发送'})).toBeEnabled()});
