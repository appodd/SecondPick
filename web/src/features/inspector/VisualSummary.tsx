import { useQuery } from "@tanstack/react-query";
import { request } from "../../api/client";
import { type VisualView } from "./VisualEvidence";
import { comparisonObservations, currentObservation, highImpact, importantObservations, validObservations } from "./visualPresentation";
import "./visual-evidence.css";

/** Existing verified projection, at most two findings per product. Read-only, no execution or ranking. */
export function VisualSummary({taskId,listingId,select,comparison=false,compact=false}:{taskId:number;listingId:number;select:(id:number)=>void;comparison?:boolean;compact?:boolean}) {
  const {data,isLoading,error}=useQuery({queryKey:["visual-evidence",taskId,listingId,undefined],retry:false,
    queryFn:()=>request<VisualView>(`/api/projects/${taskId}/listings/${listingId}/visual-evidence`),staleTime:0});
  const images=Array.isArray(data?.images)?data.images:[];
  const valid=data && Array.isArray(data.images) && Array.isArray(data.observations)?validObservations(data,taskId,listingId):[];
  const rows=(comparison?comparisonObservations(valid):importantObservations(valid)).slice(0,2);
  const review=valid.filter(o=>o.review_state==="pending_review" || highImpact.has(o.subject??""));
  const unknown=valid.filter(o=>o.status!=="visible");
  const outdated=valid.filter(o=>!currentObservation(o));
  return <section className="visual-digest" aria-label={`商品 ${listingId} 的视觉参考`}>
    {!compact?<h4>{comparison?"可比较的图片观察":"视觉发现与限制"}</h4>:null}
    {!compact||rows.length?<p className="sp-muted">{compact?'AI 图片观察 · 非独立核验':'辅助证据 · 非独立核验 · 不改变报告、覆盖或候选排序'}</p>:null}
    {isLoading?<p role="status">正在核对视觉来源…</p>:error?<p>视觉来源暂不可读；文字研究仍可使用。</p>:<>
      {rows.length?<ul>{rows.map(o=><li key={o.id}><p>{o.mode==="mock"?"离线 Mock · ":""}AI 观察：{o.visible_content}</p><p>限制：{o.uncertainty||"未提供充分局限说明，需核实"}</p><small>图片 #{o.media_id} · 研究 #{o.study_id}</small></li>)}</ul>:<p>{compact?'暂无有效图片观察，外观与配件不能据此比较。':comparison?"缺少可直接比较的当前视觉证据；未知不等于相同，不据此排名。":"暂无关联研究判断的当前重点视觉发现；不代表没有风险。"}</p>}
      {review.length?<p>有 {review.length} 条高影响或待复核观察，请核对原图；不能作为身份、数量或购买结论。</p>:null}
      {unknown.length?<p>有 {unknown.length} 条记录为看不清或未展示；未覆盖部位仍未知。</p>:null}
      {!unknown.length&&!review.length&&images.some(i=>!valid.some(o=>o.media_id===i.media_id && currentObservation(o)))?<p>部分本地图尚无当前可用逐图观察，不能据此声称已看图。</p>:null}
      {outdated.length&&!review.length?<p>历史、待复核或版本未确认的观察不作为当前事实。</p>:null}
      {data?.unavailable_images || data?.rejected_observations?<p>部分图片或来源无法验证，已降级展示。</p>:null}
    </>}
    <button type="button" onClick={()=>select(listingId)}>查看图片与逐条依据 →</button>
  </section>;
}
