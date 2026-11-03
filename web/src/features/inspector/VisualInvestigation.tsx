import {useRef,useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {request} from '../../api/client';

type Grant={enabled:boolean;allow_image_fetch:boolean;listing_ids:number[];max_requests:number;budget_usd:number;expires_at:number;provider:string;model:string};
type Item={id:number;listing_id:number;stale:boolean;plan:{media_only?:boolean;reason:string;expected_information:string|string[];media:{id:number}[]};outcome:{state?:string;image_state?:string;error?:string;study_id?:number;requires_visual_review?:boolean};media_states?:{media_id:number;state:string;sha256?:string}[];insights?:{observation_id:string;media_id:number;review_state:string;question:string}[]};
type View={items:Item[];policy:{revision:number;goal_revision:number;grant:Grant};image_fetch_enabled:boolean;execution_enabled:boolean};
const states:Record<string,string>={prepared:'图片已准备，尚未发送',fetching:'图片获取中',failed:'失败，保持未知，不自动重试',executing:'视觉分析中',completed:'观察已保存，待逐条审阅'};

export function VisualInvestigationEntry({taskId,listingId}:{taskId:number;listingId:number}){
 const [open,setOpen]=useState(false);
 return <div>{open?<VisualInvestigation taskId={taskId} listingId={listingId}/>:<button onClick={()=>setOpen(true)}>查看 Agent 视觉调查计划</button>}</div>
}

export function VisualInvestigation({taskId,listingId,select}:{taskId:number;listingId?:number;select?:(id:number)=>void}){
 const base=`/api/projects/${taskId}/visual-investigations`;
 const client=useQueryClient(),lock=useRef(false);
 const q=useQuery({queryKey:['visual-investigations',taskId,listingId],queryFn:()=>request<View>(base+(listingId?`?listing=${listingId}`:'')),retry:false});
 const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const [skipped,setSkipped]=useState<{listing_id?:number;reason:string}[]>([]);
 async function act(path:string,body:unknown){if(lock.current)return;lock.current=true;setBusy(true);setMessage('');try{const result=await request<{state?:string;skipped?:{listing_id?:number;reason:string}[]}>(base+path,{method:'POST',body:JSON.stringify(body)});if(result.skipped)setSkipped(result.skipped);await q.refetch();await client.invalidateQueries({queryKey:['visual-evidence',taskId]});await client.invalidateQueries({queryKey:['product-images',taskId]});await client.invalidateQueries({queryKey:['project',taskId]});setMessage(result.state==='failed'?'本次操作失败，保持未知；不会自动重试。':'本次操作已完成；观察仍需审阅，不自动更新报告。')}catch{setMessage('操作未完成，已停止；不会自动重试。')}finally{lock.current=false;setBusy(false)}}
 if(q.isPending)return <p>读取视觉调查计划…</p>;
 if(!q.data)return <p>视觉调查状态暂不可用；原有文字研究仍可使用。</p>;
 const data=q.data;
 return <section className="visual-approval" aria-label="Agent 视觉调查"><h3>Agent 选择性视觉调查</h3>
  <p>根据当前候选、用户关注及结构化冲突选择商品；图片获取和外部模型发送是两个独立步骤。</p>
  <button disabled={busy} onClick={()=>act('/propose',{confirmed:true,listing_ids:listingId?[listingId]:null})}>{listingId?'为此商品整理调查建议':'根据已有研究整理建议'}</button>
  {!data.items.length?<p>暂无已记录的视觉调查。无价值线索时可跳过，不会批量下载。</p>:null}
  {skipped.map((s,n)=><p key={n}>Agent 暂不主动调查{s.listing_id?` #${s.listing_id}`:''}：{s.reason}</p>)}
  {data.items.slice(0,listingId?3:3).map(i=><article key={i.id} className="visual-observation"><h4>{select?<button onClick={()=>select(i.listing_id)}>商品 #{i.listing_id}</button>:`商品 #${i.listing_id}`}</h4>
   <p>调查理由：{i.plan.reason}</p><p>{Array.isArray(i.plan.expected_information)?i.plan.expected_information.join('；'):i.plan.expected_information}</p>
   <p>图片范围：{i.plan.media.map(m=>`#${m.id}`).join(' → ')}；{i.stale?'目标已变化，不可执行':states[i.outcome.state??'']??'建议已记录，等待图片或授权'}</p>
   {i.media_states?<p>图片准备状态：{i.media_states.map(m=>`#${m.media_id} ${(({url_only:'仅有 URL',local_available:'本地字节可用',fetch_failed:'获取失败，UNKNOWN',expired:'已过期，需重新核对'} as Record<string,string>)[m.state]??'未知')}`).join('；')}。本地可用不代表模型已查看。</p>:null}
   {listingId?<div aria-label="已准备的商品原图">{i.media_states?.filter(m=>m.state==='local_available'&&m.sha256).map(m=><a key={m.media_id} href={`/api/projects/${taskId}/listings/${listingId}/visual-images/${m.media_id}?sha256=${m.sha256}`} target="_blank" rel="noreferrer"><img loading="lazy" width="96" height="96" style={{objectFit:'contain',display:'inline-block',maxWidth:'100%'}} alt={`本地原图 #${m.media_id}`} src={`/api/projects/${taskId}/listings/${listingId}/visual-images/${m.media_id}?sha256=${m.sha256}`}/></a>)}</div>:null}
   {i.outcome.image_state==='unknown'?<p>图片不可用，机况仍为 UNKNOWN；没有伪造观察。</p>:null}
   {i.outcome.requires_visual_review?<p>新增观察和待核查问题见下方逐图证据。尚未认可，不改变购买建议或排名。</p>:null}
   {i.insights?.map(x=><p key={x.observation_id}>图片 #{x.media_id} · {x.review_state==='accepted'?'人工认可的辅助线索':'AI 待审阅线索'}：{x.question} 查看对应商品逐图依据；不是独立核验。</p>)}
   {listingId&&!i.stale&&!['failed','fetching','executing','completed'].includes(i.outcome.state??'')?<button disabled={busy} onClick={()=>act(`/${i.id}/prepare`,{confirmed:true})}>准备指定图片（不发送模型）</button>:null}
   {i.plan.media_only?<p>仅为商品浏览准备缓存，不是视觉分析授权。</p>:listingId&&i.outcome.state==='prepared'?<button disabled={busy||!data.execution_enabled||!data.policy.grant.enabled} onClick={()=>act(`/${i.id}/execute`,{confirmed:true})}>按项目授权执行一次</button>:null}
  </article>)}
  <p>图片下载服务端开关：{data.image_fetch_enabled?'允许受控获取':'关闭'}；视觉执行服务端开关：{data.execution_enabled?'允许逐次校验':'关闭'}。项目配置不能绕过服务端开关。</p>
  {message?<p role="status">{message}</p>:null}
 </section>
}

export function VisualInvestigationPolicy({taskId}:{taskId:number}){
 const base=`/api/projects/${taskId}/visual-investigations`;
 const q=useQuery({queryKey:['visual-investigation-policy',taskId],queryFn:()=>request<View>(base),retry:false});
 const [enabled,setEnabled]=useState(false),[fetch,setFetch]=useState(false),[ids,setIds]=useState(''),[budget,setBudget]=useState('.25'),[count,setCount]=useState('1'),[confirm,setConfirm]=useState(false),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
 async function save(){if(!confirm||!q.data||busy)return;setBusy(true);try{
  await request(base+'/policy',{method:'PUT',body:JSON.stringify({confirmed:true,expected_revision:q.data.policy.revision,grant:{enabled,allow_image_fetch:fetch,listing_ids:ids.split(/[,，\s]+/).filter(Boolean).map(Number),max_requests:Number(count),budget_usd:Number(budget),expires_at:Date.now()/1000+3600,provider:'deepseek',model:'deepseek-flash'}})});
  setConfirm(false);setMessage('项目授权已保存，有效一小时；没有获取图片或发送模型。');await q.refetch();
 }catch{setMessage('授权未保存，检查范围与版本；未发起调用。')}finally{setBusy(false)}}
 return <details className="visual-approval"><summary>项目视觉调查设置与授权</summary>
  <p>DeepSeek / deepseek-flash。仅限明确列出的商品、当前目标及一小时有效期；保存不执行。项目暂停或全局关闭时仍拒绝执行。</p>
  {q.data?<p>已保存授权：{q.data.policy.grant.enabled?'允许限定自动视觉研究':'自动视觉研究关闭'}；版本 {q.data.policy.revision}；范围 {q.data.policy.grant.listing_ids.join('、')||'无'}。以下为本次新的完整授权，不沿用旧表单状态。</p>:<p>正在读取授权；读取失败时不能保存。</p>}
  <fieldset disabled={busy}><legend>限定范围（不会启用服务端开关）</legend>
   <label>商品 ID（逗号分隔，最多20件）<input value={ids} onChange={e=>setIds(e.target.value)}/></label>
   <label><input type="checkbox" checked={fetch} onChange={e=>setFetch(e.target.checked)}/>允许按需获取这些商品已有的图片 URL</label>
   <label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/>允许 Agent 按价值条件发送这些商品文字及图片到 DeepSeek</label>
   <label>最多模型请求数<select value={count} onChange={e=>setCount(e.target.value)}><option>1</option><option>2</option></select></label>
   <label>本地预算目标（USD，非账单硬上限）<input type="number" min="0.01" max="1" step="0.01" value={budget} onChange={e=>setBudget(e.target.value)}/></label>
   <p>每次最多三图、300秒、3000输出Token；失败不自动重试。图片可能含卖家标识；未审阅的观察不用于后续研究。</p>
   <label><input type="checkbox" checked={confirm} onChange={e=>setConfirm(e.target.checked)}/>明确确认以上范围、发送许可及费用剩余风险</label>
   <button disabled={!confirm||!q.data||busy} onClick={save}>保存本项目授权（不执行）</button>
  </fieldset>{message?<p role="status">{message}</p>:null}
 </details>
}
