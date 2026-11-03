import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it,vi} from 'vitest';
import {AutoCoverCache} from './AutoCoverCache';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
function setup(){let enabled=true,revision=0;const calls:{url:string;body:unknown;method:string}[]=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  calls.push({url,body:init?.body?JSON.parse(String(init.body)):null,method:init?.method??'GET'});
  if(init?.method==='PUT'){enabled=JSON.parse(String(init.body)).enabled;revision++}
  return new Response(JSON.stringify({enabled,revision,server_enabled:true,counts:{cached:2,queued:1,failed:0},dropped:0}));
 }));
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><AutoCoverCache taskId={3}/></QueryClientProvider>);return calls;
}
it('reads default-on display setting without downloads, approvals or model submission',async()=>{
 const calls=setup();expect(await screen.findByLabelText('自动缓存新商品封面')).toBeChecked();
 expect(calls).toEqual([{url:'/api/projects/3/cover-cache',body:null,method:'GET'}]);
});
it('disables through a version-bound preference, without restoring monitoring or research',async()=>{
 const calls=setup();fireEvent.click(await screen.findByLabelText('自动缓存新商品封面'));
 await waitFor(()=>expect(screen.getByLabelText('自动缓存新商品封面')).not.toBeChecked());
 expect(calls.filter(c=>c.method==='PUT')[0].body).toEqual({enabled:false,expected_revision:0});
 expect(calls.every(c=>c.url==='/api/projects/3/cover-cache')).toBe(true);
});
