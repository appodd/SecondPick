import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it,vi} from 'vitest';
import {VisualInvestigation,VisualInvestigationPolicy} from './VisualInvestigation';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});
function setup(mode='pending',enabled=false){
 const calls:{url:string;method:string}[]=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  calls.push({url,method:init?.method??'GET'});
  return new Response(JSON.stringify({items:mode==='empty'?[]:[{id:4,listing_id:1879,stale:false,plan:{reason:'候选有外观未知项',expected_information:'需向卖家核对',media:[{id:1}]},outcome:{state:mode}}],policy:{revision:0,grant:{enabled,listing_ids:[],max_requests:1,budget_usd:.25}},execution_enabled:false,image_fetch_enabled:false}));
 }));
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
 return {calls,wrapper:({children}:{children:React.ReactNode})=><QueryClientProvider client={client}>{children}</QueryClientProvider>};
}
it('opening investigation never posts and prepare is a separate explicit action',async()=>{
 const {calls,wrapper}=setup();render(<VisualInvestigation taskId={1} listingId={1879}/>,{wrapper});
 await screen.findByText('调查理由：候选有外观未知项');expect(calls.every(c=>c.method==='GET')).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'准备指定图片（不发送模型）'}));await waitFor(()=>expect(calls.some(c=>c.url.endsWith('/4/prepare'))).toBe(true));
 expect(calls.some(c=>c.url.endsWith('/execute'))).toBe(false);
});
it('server gate disables execution even when project grant is enabled',async()=>{
 const {wrapper}=setup('prepared',true);render(<VisualInvestigation taskId={1} listingId={1879}/>,{wrapper});
 expect(await screen.findByRole('button',{name:'按项目授权执行一次'})).toBeDisabled();
});
it('failed image preparation stays unknown without a retry button',async()=>{
 const {wrapper}=setup('failed');render(<VisualInvestigation taskId={1} listingId={1879}/>,{wrapper});
 await screen.findByText(/失败，保持未知/);expect(screen.queryByRole('button',{name:'准备指定图片（不发送模型）'})).not.toBeInTheDocument();
});
it('policy save requires explicit consent and does not execute',async()=>{
 const {calls,wrapper}=setup();render(<VisualInvestigationPolicy taskId={1}/>,{wrapper});
 fireEvent.click(screen.getByText('项目视觉调查设置与授权'));await screen.findByText(/已保存授权/);
 const save=screen.getByRole('button',{name:'保存本项目授权（不执行）'});expect(save).toBeDisabled();
 fireEvent.click(screen.getByLabelText('明确确认以上范围、发送许可及费用剩余风险'));fireEvent.click(save);
 await waitFor(()=>expect(calls.some(c=>c.url.endsWith('/policy')&&c.method==='PUT')).toBe(true));
 expect(calls.some(c=>/execute|prepare/.test(c.url))).toBe(false);
});
