import {useRef,useState} from 'react';
import {request} from '../../api/client';
import type {VisualView} from './VisualEvidence';
type Preview={approval_id:string;scope_sha256:string;expires_at:number;scope:{listing_id:number;goal_revision:number;provider:string;model:string;purpose:string;images:VisualView['images'];text_input:unknown;instructions:string;request_sha256:string;cost_estimate:{usd:number;notice:string;price_snapshot:string};timeout_seconds:number;max_output_tokens:number}};
export function VisualActions({data,base,refresh}:{data:VisualView;base:string;refresh:()=>void}){
 const [selected,setSelected]=useState<number[]>([]),[preview,setPreview]=useState<Preview>(),[ticket,setTicket]=useState<string>();
 const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[consent,setConsent]=useState(false),[follow,setFollow]=useState(false);
 const lock=useRef(false);
 const [purpose,setPurpose]=useState('按当前目标观察指定图片的可见内容，不执行其他操作。');
 const clear=()=>{setPreview(undefined);setTicket(undefined);setConsent(false);};
 async function act(kind:'preview'|'confirm'|'execute'|'research'){
  if(lock.current)return;lock.current=true;setBusy(true);setMessage('');
  try{
   if(kind==='preview'){clear();setPreview(await request<Preview>(base+'/visual-approval/preview',{method:'POST',body:JSON.stringify({media_ids:selected,purpose})}));}
   if(kind==='confirm'&&preview){const r=await request<{execution_ticket:string;notice:string}>(base+'/visual-approval/confirm',{method:'POST',body:JSON.stringify({approval_id:preview.approval_id,scope_sha256:preview.scope_sha256,confirmed:true})});setTicket(r.execution_ticket);setMessage('范围已确认，尚未执行；需要下方独立执行操作。');}
   if(kind==='execute'&&preview&&ticket&&consent){const current=ticket;setTicket(undefined);setConsent(false);const r=await request<{state:string;valid_observations?:number;error_code?:string}>(base+'/visual-analysis/execute',{method:'POST',body:JSON.stringify({execution_ticket:current,scope_sha256:preview.scope_sha256,execution_confirmed:true,upload_authorized:true,downstream_text_authorized:true,budget_accepted:true})});const reasons:Record<string,string>={visual_provider_timeout:'服务商请求超时',visual_provider_http_error:'服务商返回 HTTP 错误',visual_provider_invalid_json:'服务商响应不是有效 JSON',visual_reference_or_structure_invalid:'图片引用或观察结构未通过校验',visual_provider_response_invalid:'服务商模型或响应结构不符合要求',visual_credentials_unavailable:'安全凭据不可用',visual_preflight_failed:'执行前绑定校验失败',visual_provider_transport_failed:'传输失败'};setMessage(r.state==='completed'?'视觉分析完成，请逐条审阅；没有启动文字研究。':`视觉分析未成功，已停止；${reasons[r.error_code??'']??'结果未通过校验'}。不会自动重试，文字研究仍可使用。`);clear();refresh();}
   if(kind==='research'&&follow){setFollow(false);await request(base+'/visual-evidence/research',{method:'POST',body:JSON.stringify({confirmed:true,expected_goal_revision:data.goal_revision,observation_ids:data.accepted_observation_ids,dependency_signature:data.dependency_signature,request_key:crypto.randomUUID()})});setMessage('已明确提交一次后续文字研究；没有重新发送图片或整合报告。');refresh();}
  }catch(e){setMessage(e instanceof Error?e.message:'操作失败，已停止；不会自动重试。');clear();}finally{lock.current=false;setBusy(false);}
 }
 return <div className="visual-approval" aria-label="主动视觉分析">
  <h4>主动视觉分析</h4><p>{data.execution_enabled?'服务端允许独立执行；仍需逐次授权。':'服务端真实执行开关关闭；配置启用和确认范围不会上传或执行。'}</p>
  <fieldset disabled={busy}><legend>选择本次图片（按选择顺序，最多三张）</legend>{data.images.map(i=><label key={i.media_id}><input type="checkbox" checked={selected.includes(i.media_id)} disabled={!selected.includes(i.media_id)&&selected.length>=3} onChange={e=>{setSelected(e.target.checked?[...selected,i.media_id]:selected.filter(x=>x!==i.media_id));clear();}}/>图片 #{i.media_id} · {i.width}×{i.height}<small>来源：{i.source_url} · SHA-256 {i.sha256}</small></label>)}</fieldset>
  <label>本次观察用途<input value={purpose} maxLength={500} disabled={busy} onChange={e=>{setPurpose(e.target.value);clear();}}/></label>
  <button disabled={busy||!selected.length||!data.approval_allowed||!purpose.trim()} onClick={()=>act('preview')}>审查图片分析范围</button>
  {!data.approval_allowed?<p>{data.approval_blocked_reason}</p>:null}
  {preview?<fieldset disabled={busy}><legend>冻结输入与执行范围</legend><p>商品 #{preview.scope.listing_id} · 目标 v{preview.scope.goal_revision} · {preview.scope.provider} / {preview.scope.model}</p>
   <p>图片顺序：{preview.scope.images.map(x=>`#${x.media_id}`).join(' → ')}；{preview.scope.timeout_seconds} 秒；最多 {preview.scope.max_output_tokens} 输出 Token。</p>
   <p>本地估算 ${preview.scope.cost_estimate.usd}（价格快照 {preview.scope.cost_estimate.price_snapshot}）。{preview.scope.cost_estimate.notice}</p>
   <details><summary>即将发送的文字、提示词与图片哈希</summary><pre>{JSON.stringify(preview.scope.text_input,null,2)}</pre><pre>{preview.scope.instructions}</pre>{preview.scope.images.map(i=><p key={i.media_id}>#{i.media_id} · {i.sha256}</p>)}<p>请求 SHA-256：{preview.scope.request_sha256}</p></details>
   <p>有效期至 {new Date(preview.expires_at*1000).toLocaleTimeString()}。图片和文字可能含卖家信息；只发送本次冻结范围。</p>
   {!ticket?<button onClick={()=>act('confirm')}>确认范围，暂不执行</button>:<><label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>我授权发送本次文字与图片，接受估算费用及风险；结果仍须人工审阅，不自动研究。</label><button disabled={!consent||!data.execution_enabled} onClick={()=>act('execute')}>执行一次视觉分析</button></>}
   <button onClick={clear}>取消范围</button></fieldset>:null}
  {busy?<p role="status">正在处理当前操作，请勿重复提交；视觉执行不自动重试…</p>:null}{message?<p role="status">{message}</p>:null}
  {data.accepted_observation_ids?.length?<fieldset disabled={busy}><legend>后续文字研究</legend><p>仅使用此商品 {data.accepted_observation_ids.length} 条当前有效且人工认可的观察；不重新发图、不自动更新报告。</p><label><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>明确使用这些辅助证据发起后续研究</label><button disabled={!follow} onClick={()=>act('research')}>使用认可证据研究此商品</button></fieldset>:null}
 </div>;
}
