import {useRef,useState} from 'react';
import {request} from '../../api/client';
import type {VisualObservation} from './visualPresentation';
export function ObservationReview({o,base,refresh}:{o:VisualObservation;base:string;refresh:()=>void}){
 const [reason,setReason]=useState(''),[edit,setEdit]=useState(false),[content,setContent]=useState(o.visible_content),[inference,setInference]=useState(o.limited_inference),[limit,setLimit]=useState(o.uncertainty),[busy,setBusy]=useState(false),[message,setMessage]=useState('');const lock=useRef(false);
 async function submit(action:'accept'|'correct'|'defer'|'reject'){
  if(lock.current)return;lock.current=true;setBusy(true);setMessage('');
  try{await request(`${base}/visual-observations/${o.study_id}/review`,{method:'POST',body:JSON.stringify({observation_id:o.id,action,reason,expected_revision:o.review_revision??0,...(action==='correct'?{visible_content:content,limited_inference:inference,uncertainty:limit}:{})})});setMessage('审阅已保存；原始输出保留，没有启动研究。');setEdit(false);refresh();}catch(e){setMessage(e instanceof Error?e.message:'审阅未保存');}finally{lock.current=false;setBusy(false);}
 }
 return <div aria-label="人工审阅观察">{o.original_visible_content!==undefined?<details><summary>原始模型描述（不覆盖）</summary><p>{o.original_visible_content}</p><p>原始推断：{o.original_limited_inference}</p><p>原始限制：{o.original_uncertainty}</p></details>:null}
  <p>人工审阅：{({accept:'已接受',correct:'已修正并认可',defer:'暂缓',reject:'已拒绝'} as Record<string,string>)[o.human_review_action??'']??'尚未认可'}；AI 观察不是独立核验。</p>
  <label>审阅理由<input value={reason} maxLength={1000} disabled={busy} onChange={e=>setReason(e.target.value)}/></label>
  {edit?<fieldset><legend>修正表述（保留原文）</legend><label>可见内容<textarea value={content} maxLength={1500} onChange={e=>setContent(e.target.value)}/></label><label>有限推断<textarea value={inference} maxLength={1000} onChange={e=>setInference(e.target.value)}/></label><label>限制与不确定性<textarea value={limit} maxLength={1000} onChange={e=>setLimit(e.target.value)}/></label><button disabled={busy||!reason.trim()||!limit.trim()} onClick={()=>submit('correct')}>保存修正并认可</button></fieldset>:null}
  <div><button disabled={busy||!reason.trim()||o.review_state==='historical'} onClick={()=>submit('accept')}>接受观察</button><button disabled={busy||o.review_state==='historical'} onClick={()=>setEdit(!edit)}>修正表述</button><button disabled={busy||!reason.trim()} onClick={()=>submit('defer')}>暂缓观察</button><button disabled={busy||!reason.trim()} onClick={()=>submit('reject')}>拒绝观察</button></div>
  {o.review_history?.length?<details><summary>审阅历史（{o.review_history.length}）</summary>{o.review_history.map((r,i)=><p key={i}>v{r.revision} · {r.action} · {r.reason}</p>)}</details>:null}{message?<p role="status">{message}</p>:null}
 </div>;
}
