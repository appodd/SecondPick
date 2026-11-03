import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it,vi} from 'vitest';
import {ProductMediaGallery} from './ProductMediaGallery';
const hash='a'.repeat(64),base='/api/tasks/1/listings/1879/images';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
function setup(state='local_available'){
 const calls:{url:string;method:string}[]=[];let cached=state==='local_available';
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  calls.push({url,method:init?.method??'GET'});
  if(url.endsWith('/prepare-preview'))return new Response(JSON.stringify({ticket:'single-image-ticket-123456',media:[{id:2,source_url:'https://img.alicdn.com/real.webp'}],expires_at:9999999999,notice:'图片获取，不发模型',model_authorized:false}));
  if(url.endsWith('/prepare')){cached=true;return new Response(JSON.stringify({state:'prepared'}))}
  return new Response(JSON.stringify({listing_id:1879,state:cached?'local_available':state,source_count:state==='source_missing'?0:1,local_count:cached?1:0,preparation_enabled:true,source_signature:hash,images:state==='source_missing'?[]:[{id:2,url:'https://img.alicdn.com/real.webp',created_at:'2026-10-27',display_url:cached?base+'/2/content?sha256='+hash:null,state:cached?'local_available':'not_prepared'}]}));
 }));
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
 render(<QueryClientProvider client={client}><ProductMediaGallery taskId={1} listingId={1879} title="商品实图"/></QueryClientProvider>);
 return calls;
}
it('renders local bytes without exposing remote URLs to img requests or posting',async()=>{
 const calls=setup();await screen.findByText('1 张可浏览 · 1 条已存来源');
 expect(screen.getByRole('img',{name:'商品实图'})).toHaveAttribute('src',expect.stringContaining('/images/2/content?sha256='));
 expect(calls.every(c=>c.method==='GET')).toBe(true);
});
it('history without a source is not a loading failure',async()=>{
 setup('source_missing');await screen.findByText(/历史采集未保存商品图片来源/);
 expect(screen.queryByText(/图片获取失败/)).not.toBeInTheDocument();expect(screen.queryByText('按需准备图片（只下载，不看图）')).not.toBeInTheDocument();
});
it('URL-only data is explicitly unprepared and never loaded as external image',async()=>{
 const calls=setup('not_prepared');await screen.findByText(/已保存图片链接，尚无可浏览缓存/);
 expect(document.querySelector('img[src]')).toBeNull();expect(calls).toHaveLength(1);
});
it('two explicit image-only actions update the gallery without submitting a model',async()=>{
 const calls=setup('not_prepared');await screen.findByText(/已保存图片链接/);
 fireEvent.click(screen.getByText('按需准备图片（只下载，不看图）'));
 fireEvent.click(screen.getByLabelText(/图片 #2/));fireEvent.click(screen.getByRole('button',{name:'审查图片获取范围'}));
 await screen.findByText('本次图片获取确认');expect(calls.some(c=>c.url.endsWith('/prepare'))).toBe(false);
 expect(screen.getByRole('button',{name:'确认准备图片'})).toBeDisabled();fireEvent.click(screen.getByLabelText('仅授权获取上述图片，不授权任何模型分析'));
 fireEvent.click(screen.getByRole('button',{name:'确认准备图片'}));await screen.findByText('图片已准备；没有上传模型或启动研究。');
 await screen.findByText('1 张可浏览 · 1 条已存来源');expect(calls.filter(c=>c.url.endsWith('/prepare'))).toHaveLength(1);
 expect(calls.some(c=>/execute|research|vision/.test(c.url))).toBe(false);
});
