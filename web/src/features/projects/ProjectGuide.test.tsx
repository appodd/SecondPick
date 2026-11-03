import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {ProjectGuide,projectGuide} from './ProjectGuide';
import type {ProjectOverview} from '../../api/projectClient';
import type {Monitor,MonitorPage} from '../../api/monitorClient';
function data():ProjectOverview{return {project:{id:1,title:'测试选购',goal:'预算内选购',status:'active'},policy:{budget:400,hard:[],soft:[],minimum:20,paused:0,auto_research:0},phase:'collecting_baseline',total:0,eligible:0,pending:0,coverage:{evaluated:0,waiting:0},report:null,cards:[],favorites:[],changes:[],studies:[]};}
const page=(state?:Monitor['state']):MonitorPage=>({enabled:true,platform_enabled:true,candidate_pool_count:0,items:state?[{id:1,state} as Monitor]:[]});
beforeEach(()=>{localStorage.clear();vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(page()),{status:200})))});
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
describe('real state guide projection',()=>{
 it('new project with no monitors points to existing monitor flow',()=>{const g=projectGuide(data(),page());expect(g.kind).toBe('no_monitor');expect(g.view).toBe('monitors')});
 it('running monitor describes actual counts without claiming research',()=>{const d=data();d.total=7;d.eligible=3;const g=projectGuide(d,page('running'));expect(g.kind).toBe('collecting');expect(g.description).toContain('7 件');expect(g.description).toContain('3 件');expect(g.description).toContain('20 件');expect(g.view).toBe('products')});
 it('threshold suggests scope confirmation, never creates work',()=>{const d=data();d.total=25;d.eligible=20;const g=projectGuide(d,page('stopped'));expect(g.kind).toBe('sample_ready');expect(g.view).toBe('research');expect(g.description).toContain('不会自动提交')});
 it.each(['running','queued'] as const)('tracks %s research with the existing journey',state=>{const d=data();d.studies=[{id:1,state,kind:'initial'} as ProjectOverview['studies'][number]];expect(projectGuide(d,page()).kind).toBe(state)});
 it('paused research stays paused even if collection runs',()=>{const d=data();d.policy.paused=1;expect(projectGuide(d,page('running')).kind).toBe('paused')});
 it('unknown or failed monitor read cannot claim collection is running',()=>{expect(projectGuide(data()).kind).toBe('monitor_unknown');expect(projectGuide(data(),page('needs_attention')).kind).toBe('monitor_attention');expect(projectGuide(data(),page('paused')).kind).toBe('monitor_idle')});
 it('missing goal directs to current overview rather than creating monitor',()=>{expect(projectGuide(data(),page(),true).kind).toBe('goal')});
 it('saved report with no candidates does not invent comparison options',()=>{const d=data();d.report={id:1,content:'已有结论',candidate_ids_json:'[]',limited:1,evidence_current:true} as ProjectOverview['report'];const g=projectGuide(d,page());expect(g.view).toBe('research');expect(g.description).toContain('没有可展示的报告候选')});
 it('historical report remains a caution rather than latest result',()=>{const d=data();d.report={id:1,content:'旧报告',candidate_ids_json:'[]',evidence_current:false} as ProjectOverview['report'];expect(projectGuide(d,page()).kind).toBe('attention')});
});
describe('guide lifecycle and safe navigation',()=>{
 function mount(d=data()){const go=vi.fn(),cache=new QueryClient({defaultOptions:{queries:{retry:false}}});const wrap=(v:ProjectOverview)=><QueryClientProvider client={cache}><ProjectGuide key={v.project.id} data={v} go={go}/></QueryClientProvider>;const result=render(wrap(d));return {go,...result,update:(v:ProjectOverview)=>result.rerender(wrap(v))};}
 it('first empty project shows five page responsibilities without an inner disclosure or duplicate action',()=>{const {go}=mount();const guide=screen.getByRole('complementary');expect(guide.querySelector('details')).toBeNull();expect(guide.querySelectorAll('nav button')).toHaveLength(5);expect(screen.getByText('五个页面分别做什么？')).toBeVisible();expect(screen.queryByRole('heading',{name:'目标已保存，下一步设置监控'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:/监控任务/}));expect(go).toHaveBeenCalledWith('monitors');expect(fetch).not.toHaveBeenCalled()});
 it('closing and reopening preserves project preference',()=>{mount();fireEvent.click(screen.getByRole('button',{name:'关闭指南'}));expect(screen.queryByRole('complementary')).toBeNull();expect(localStorage.getItem('secondpick:project-guide:1')).toBe('dismissed');fireEvent.click(screen.getByRole('button',{name:'项目使用指南'}));expect(screen.getByText('五个页面分别做什么？')).toBeVisible()});
 it('daily existing project stays compact until requested',()=>{const d=data();d.total=5;mount(d);expect(screen.getByRole('button',{name:'项目使用指南'})).toBeVisible();expect(screen.queryByRole('complementary')).toBeNull();expect(fetch).not.toHaveBeenCalled()});
 it('sample changes do not turn page introductions into another next-step card',()=>{const {update}=mount();const d=data();d.eligible=20;d.total=20;update(d);expect(screen.getByRole('navigation',{name:'了解项目页面'})).toBeVisible();expect(screen.queryByRole('heading',{name:'样本已达到设定数量'})).toBeNull()});
 it('switching projects does not copy dismissed preference',()=>{const {update}=mount();fireEvent.click(screen.getByRole('button',{name:'关闭指南'}));const d=data();d.project.id=2;update(d);expect(screen.getByRole('button',{name:'关闭指南'})).toBeVisible();expect(localStorage.getItem('secondpick:project-guide:1')).toBe('dismissed');expect(localStorage.getItem('secondpick:project-guide:2')).toBe('open')});
 it('new user can refresh after samples arrive without losing the open guide',()=>{const first=mount();first.unmount();const d=data();d.total=5;mount(d);expect(screen.getByRole('button',{name:'关闭指南'})).toBeVisible()});
});
