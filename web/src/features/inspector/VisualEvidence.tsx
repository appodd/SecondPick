import { VisualActions } from "./VisualActions";
import { VisualInvestigationEntry } from "./VisualInvestigation";
import { ObservationReview } from "./ObservationReview";
import { useQuery } from "@tanstack/react-query";
import { request } from "../../api/client";
import { validObservations, highImpact, type VisualObservation } from "./visualPresentation";
import "./visual-evidence.css";

export interface VisualView {
  task_id:number; listing_id:number; goal_revision:number; state:string;
  approval_allowed:boolean; approval_blocked_reason:string; execution_enabled:boolean;
  images:{media_id:number; sha256:string; width:number; height:number; source_url:string}[];
  observations:{id:string; listing_id:number; study_id:number; run_id:string; media_id:number; sha256:string;
    visible_content:string; limited_inference:string; uncertainty:string; status:string; provider:string; model:string;
    review_state:string; independently_verified:false; mode:string; freshness?:"fresh"|"stale"|"invalid"|"unknown";freshness_reasons?:string[];
    subject?:string;affects_criteria?:string[];origin?:string;source_type?:string;review_reason?:string;
    original_visible_content?:string;original_limited_inference?:string;original_uncertainty?:string;human_review_action?:string;review_revision?:number;review_history?:{revision:number;action:string;reason:string}[];
    references:{study_id:number; criterion_id:string; status:string}[]}[];
  dependency_signature?:string;accepted_observation_ids?:string[];
  rejected_observations:number; unavailable_images:number;
  failures:{study_id:number; state:string; reason:string;error_code?:string}[];
  visual_decision?:{action:string;state:string;reasons:string[];gates:string[];reusable_observation_ids:string[];execution_enabled:false;dependent_studies?:{study_id:number;state:string;observation_ids:string[]}[]};
}


const freshnessReasons:Record<string,string>={
  same_pixels_goal_and_analysis:"图片、目标与分析版本一致",image_content_changed:"图片内容已变化",goal_changed:"选购目标已变化",
  item_evidence_changed:"商品文字或身份绑定已变化",analysis_model_changed:"视觉模型配置已变化",
  analysis_instructions_sha256_changed:"观察指令已变化",analysis_schema_sha256_changed:"观察协议已变化",analysis_purpose_changed:"观察用途已变化",
  observation_rejected_or_revoked:"观察已被标无效或撤销",observation_questioned:"观察存在人工异议",requires_human_review:"该观察尚待人工复核",
  original_image_unavailable:"原图片内容暂不可验证",analysis_version_unrecorded:"历史记录没有分析版本指纹",current_model_unknown:"当前模型配置无法确认",
  valid_uncertainty_not_positive_evidence:"只记录看不清或未展示，不作为符合条件的依据"
};

export function VisualEvidence({taskId,listingId,studyId,referencedByStudy,onQuestion}:{taskId:number;listingId?:number;studyId?:number;referencedByStudy?:number;onQuestion?:(o:VisualObservation)=>void}) {
  const base=`/api/projects/${taskId}/listings/${listingId}`;
  const query=useQuery({queryKey:["visual-evidence",taskId,listingId,studyId],retry:false,
    queryFn:()=>request<VisualView>(studyId?`/api/projects/${taskId}/visual-studies/${studyId}`:`${base}/visual-evidence`),staleTime:0});
  const data=query.data;
  if(query.isLoading)return <section className="inspector-block"><h3>图片观察与审批</h3><p role="status">正在读取本地视觉证据…</p></section>;
  if(query.error||!data||!Array.isArray(data.images)||!Array.isArray(data.observations))return <section className="inspector-block"><h3>图片观察与审批</h3><p role="status">视觉证据暂不可用；原文字研究不受影响。</p></section>;
  const imageUrl=(media:number,hash:string)=>`/api/projects/${taskId}/listings/${data.listing_id}/visual-images/${media}?sha256=${encodeURIComponent(hash)}`;
  const resolvedBase=`/api/projects/${taskId}/listings/${data.listing_id}`;
  const validated=validObservations(data,taskId,listingId);
  const observations=validated.filter(o=>referencedByStudy===undefined || o.references?.some(r=>r.study_id===referencedByStudy));
  return <section className="inspector-block visual-evidence" aria-label="图片观察与审批">
    <h3>图片观察与审批</h3><p>卖家声明、未检查图片、AI 图片观察与独立核验是不同证据。AI 看图不等于实物已核验。</p>
    {!studyId&&referencedByStudy===undefined&&listingId!==undefined?<VisualInvestigationEntry taskId={taskId} listingId={listingId}/>:null}
    {referencedByStudy!==undefined?<p>仅列出研究 #{referencedByStudy} 实际引用且当前可追溯的观察；原始判断保留，失效来源不会补造成有效证据。</p>:null}
    {data.visual_decision?<div aria-label="视觉研究决策"><p>{data.visual_decision.reasons.join("；")}</p>
      <p>当前可复用 {data.visual_decision.reusable_observation_ids.length} 条观察。决策不会自动执行或安排研究。</p>
      {data.visual_decision.dependent_studies?.some(s=>s.state!=="fresh")?<p role="status">已有研究判断引用的视觉证据需要重新评估；原结果保留，不自动复评或整合报告。</p>:null}
      {data.visual_decision.action==="needs_analysis"&&data.visual_decision.gates.length?<p>仍需满足审批、预算或当前调度条件；本阶段不开放真实执行。</p>:null}</div>:null}
    {!observations.length?<p className="le-empty">暂无有效 AI 图片观察。{data.images.length?"已有本地图片，尚无可用观察。":"仅有 URL 或缺少通过校验的本地图。"}</p>:null}
    {observations.map(o=><article key={o.id} className="visual-observation">
      <h4>商品 #{o.listing_id} · 图片 #{o.media_id}</h4><img src={imageUrl(o.media_id,o.sha256)} alt={`观察依据：商品 ${o.listing_id} 的图片 ${o.media_id}`} loading="lazy"/>
      <p className="visual-state">{o.mode==="mock"?"离线 Mock · ":""}AI 图片观察 · 非独立核验 · {o.review_state==="pending_review"?"待人工复核，未用于判断":o.review_state==="historical"?"历史版本，非当前证据":o.review_state==="not_accepted"?"人工未接受，未用于判断":"引用校验通过"}</p>
      {o.freshness?<p>研究新鲜度：{({fresh:"当前可复用",stale:"需要重新评估或复核",invalid:"证据无效",unknown:"缺少版本信息，暂不能确认"})[o.freshness]}</p>:null}
      <p>{o.status==="unreadable"?"看不清，无法判断":o.status==="not_shown"?"该部位未展示":o.visible_content}</p>
      {o.limited_inference?<p>有限推断：{o.limited_inference}</p>:null}<p>观察限制：{o.uncertainty}</p>
      {highImpact.has(o.subject??"")?<p className="visual-caution">高影响观察：包装印刷图、数量、身份及内部状态须另行核实，人工接受也不等于独立验真。</p>:null}
      {o.review_reason?<p>复核说明：{o.review_reason}</p>:null}
      <p><a href={imageUrl(o.media_id,o.sha256)} target="_blank" rel="noreferrer">查看来源图片 #{o.media_id}</a>{onQuestion?<button type="button" onClick={()=>onQuestion(o)}>就这条观察准备追问</button>:null}</p>
      {onQuestion?<p className="sp-muted">仅打开问题草稿，不发送图片、不提交研究。是否采用观察仍需核对来源。</p>:null}
      <ObservationReview key={`${o.id}:${o.review_revision??0}`} o={o} base={resolvedBase} refresh={()=>{void query.refetch();}}/>
      <details><summary>图片来源、版本与研究引用</summary><p>{o.provider} / {o.model} · 研究 #{o.study_id} · 运行 {o.run_id}</p><p>SHA-256：<code>{o.sha256}</code></p><p>{data.images.find(i=>i.media_id===o.media_id)?.source_url}</p>
        {o.freshness_reasons?.length?<p>版本检查：{o.freshness_reasons.map(reason=>freshnessReasons[reason]??"观察绑定或版本未通过当前检查").join("；")}</p>:null}
        <p>观察标识：<code>{o.id}</code></p>
        {o.references?.length?<ul>{o.references.map((r,i)=><li key={i}><a href={`/projects/${taskId}?view=research#research-run-${r.study_id}`}>研究 #{r.study_id}</a> · 条件 {r.criterion_id} · {r.status}（原快照引用，不代表当前仍有效）</li>)}</ul>:<p>尚无研究判断引用此观察。</p>}</details>
    </article>)}
    {data.rejected_observations||validated.length!==data.observations.length?<p role="status">部分记录未通过归属或版本校验，未作为视觉事实展示。</p>:null}
    {data.unavailable_images?<p>部分图片只有 URL、缺失或未通过本地校验。</p>:null}
    {data.images.some(i=>!validated.some(o=>o.media_id===i.media_id && o.freshness==='fresh' && o.review_state==='accepted'))?<details><summary>尚无当前可用观察的本地图片</summary><p>本地文件或浏览器预览不等于模型实际查看，也不证明图片内容已核实。</p>
      {data.images.filter(i=>!validated.some(o=>o.media_id===i.media_id && o.freshness==='fresh' && o.review_state==='accepted')).map(i=><p key={i.media_id}><a href={imageUrl(i.media_id,i.sha256)} target="_blank" rel="noreferrer">本地图片 #{i.media_id}</a> · {i.width}×{i.height} · <code>{i.sha256}</code></p>)}</details>:null}
    {data.failures?.map(f=><p key={f.study_id}>研究 #{f.study_id}：{f.reason}</p>)}
    {!studyId&&referencedByStudy===undefined?<VisualActions key={`${taskId}:${listingId}`} data={data} base={resolvedBase} refresh={()=>{void query.refetch();}}/>:null}
  </section>;
}
