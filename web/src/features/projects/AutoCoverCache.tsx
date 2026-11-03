import {useRef,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {request} from '../../api/client';

type View={enabled:boolean;revision:number;server_enabled:boolean;counts:Record<string,number>;dropped:number};
export function AutoCoverCache({taskId}:{taskId:number}){
 const key=`/api/projects/${taskId}/cover-cache`,lock=useRef(false);
 const q=useQuery({queryKey:['cover-cache',taskId],queryFn:()=>request<View>(key),retry:false,refetchInterval:5000});
 const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
 async function toggle(enabled:boolean){if(lock.current||!q.data)return;lock.current=true;setBusy(true);setMessage('');try{
  await request(key,{method:'PUT',body:JSON.stringify({enabled,expected_revision:q.data.revision})});await q.refetch();
  setMessage(enabled?'自动封面已开启，仅处理之后新入库商品。':'自动封面已关闭，排队任务取消；已发出的请求无法撤回。');
 }catch{setMessage('未保存，请刷新状态后再操作。')}finally{lock.current=false;setBusy(false)}}
 return <details className="sp-auto-cover sp-disclosure"><summary>商品封面缓存 · {typeof q.data?.enabled==='boolean'?(q.data.enabled?'默认开启':'已关闭'):'状态待读取'}</summary>
  <p>监控发现新商品时，后台自动准备一张真实商品图片供列表展示。不会自动调用 AI 视觉分析；不会补抓历史商品。</p>
  {typeof q.data?.enabled==='boolean'?<><label><input type="checkbox" checked={q.data.enabled} disabled={busy} onChange={e=>toggle(e.target.checked)}/>自动缓存新商品封面</label>
   {!q.data.server_enabled?<p>服务端封面缓存已关闭，当前不会下载。</p>:null}
   <p>已缓存 {q.data.counts?.cached??0} · 等待 {q.data.counts?.queued??0} · 准备中 {q.data.counts?.fetching??0} · 失败 {q.data.counts?.failed??0}</p>
   {q.data.dropped?<p>有 {q.data.dropped} 次入队达到容量限制，保留未准备状态，可按需手动准备。</p>:null}
  </>:<p>无法确认当前配置时不会替你切换。<button onClick={()=>q.refetch()}>刷新封面状态</button></p>}
  {message?<p role="status">{message}</p>:null}
 </details>
}
