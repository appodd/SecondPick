import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Bookmark, Check, Columns3, Sparkles, X } from "lucide-react";
import { useGoalContinuity } from "./GoalContinuity";
import { marketHref } from "../market/marketAnalysis";
import { useContextHref } from "./contextNavigation";
import { projectApi, type ProjectOverview } from "../../api/projectClient";
import { Panel, price, date, ProductThumbnail } from "./projectUi";
import { useProjectAgent } from "./ProjectAgent";
import { comparisonIds, comparisonLimit, decisionCandidates, type DecisionCandidate } from "./candidateDecision";
import { reportCandidateIds } from "./overviewReport";
import { DecisionEvidence } from "./DecisionEvidence";
import { ConditionJudgments } from "../conversation/ConditionJudgments";
import { MarketReferenceSummary } from "../market/MarketReferenceSummary";
import { VisualSummary } from "../inspector/VisualSummary";
import "./shopping-workbench.css";

export function Shortlist({data,select,action}:{data:ProjectOverview;select:(id:number)=>void;action:(fn:()=>Promise<unknown>)=>Promise<void>}) {
  const [params,setParams]=useSearchParams(),agent=useProjectAgent(),goal=useGoalContinuity();
  const sourceReady=goal.state==='unversioned';
  const decisions=useMemo(()=>decisionCandidates(data,sourceReady),[data,sourceReady]);
  const compare=comparisonIds(params.get('compare'),data), selected=compare.map(id=>decisions.get(id)!);
  const source=['report','saved'].includes(params.get('collection')??'')?params.get('collection')!:'all';
  const rawNominations=reportCandidateIds(data.report), nominated=rawNominations??[];
  const nominatedAvailable=nominated.filter(id=>decisions.has(id));
  const saved=data.favorites.filter(id=>decisions.has(id));
  const ids=[...new Set([...nominatedAvailable,...saved])];
  const visible=(source==='report'?nominatedAvailable:source==='saved'?saved:ids).map(id=>decisions.get(id)!);
  const reportStale=!!data.report&&(goal.state!=='unversioned'||data.goal_context?.report_current!==true||data.report.goal_revision!==data.goal_context?.current_revision||data.report.evidence_current===false);
  const reportChanged=!!data.report&&(data.report.evidence_current===false||data.goal_context?.report_current===false||data.report.goal_revision!==undefined&&data.goal_context?.current_revision!==undefined&&data.report.goal_revision!==data.goal_context.current_revision);
  const comparison=useRef<HTMLElement>(null),lock=useRef(false);
  const [saving,setSaving]=useState<number>();
  function update(values:Record<string,string|undefined>){const next=new URLSearchParams(params);for(const [k,v] of Object.entries(values))if(v===undefined)next.delete(k);else next.set(k,v);setParams(next,{replace:true})}
  function setCompare(ids:number[]){update({compare:ids.length?ids.join(','):undefined})}
  function toggle(id:number){setCompare(compare.includes(id)?compare.filter(n=>n!==id):compare.length<comparisonLimit?[...compare,id]:compare)}
  const contextual=useContextHref(data.project.id);
  function ask(item:DecisionCandidate){agent.open({role:'products',ids:[item.card.listing_id],label:`商品 #${item.card.listing_id}；${item.basis==='report'?'报告当时判断，需核对当前适用性':'当前已保存证据'}；仅准备追问`,question:'这件商品最值得核实的风险和未知是什么？哪些补充证据会改变购买判断？',report:item.basis==='report'?data.report:undefined})}
  function aiCompare(){if(compare.length<2||compare.length>comparisonLimit)return;agent.open({role:'decision',ids:compare,label:`明确选中的 ${compare.length} 件商品；${reportStale?'报告适用性需重新核对':'当前项目已保存证据'}；不是全库最新排名`,report:data.report,question:'比较这些商品的依据、风险和未知项，哪些信息会改变购买判断？'})}
  async function favorite(item:DecisionCandidate){if(lock.current)return;lock.current=true;setSaving(item.card.listing_id);try{await action(()=>projectApi.favorite(data.project.id,item.card.listing_id,!item.saved))}finally{lock.current=false;setSaving(undefined)}}
  function badges(item:DecisionCandidate){return <div className="ux2-origin-tags">{item.nominated?<span className={reportStale?'ux2-tag ux2-tag-warn':'ux2-tag'}>报告 #{data.report?.id} 候选{reportStale?reportChanged?' · 历史参考':' · 适用性待确认':''}</span>:null}{item.saved?<span className="ux2-tag ux2-tag-saved"><Bookmark size={11}/> 我的收藏</span>:null}</div>}
  function basis(item:DecisionCandidate){return item.basis==='current'?'当前目标下的逐项判断':item.basis==='report'?'报告当时的判断 · 适用性需核对':'暂无可用逐项判断'}
  return <div className="ux2-shortlist">
    <section className={`ux2-list-context${reportStale?' is-stale':''}`} aria-label="候选来源与新鲜度">
      <div><h2>候选来源</h2><p>{data.report?`报告 #${data.report.id} · ${date(data.report.created_at)} · ${nominatedAvailable.length} 件报告候选`:'尚无报告候选'} · {saved.length} 件收藏</p></div>
      <div className="ux2-context-note">{data.policy.paused?<span className="ux2-tag ux2-tag-warn">研究已暂停</span>:null}<p role={reportStale?'status':undefined}>{reportStale?reportChanged?'推荐来自历史报告，目标或证据已变化，需重新核对。':'报告的目标或证据版本暂无法确认，适用性待确认。':'推荐基于报告当时的样本，不是全库最新排名。'}{data.pending>0?` 另有 ${data.pending} 件当前信息未纳入报告。`:''}</p></div>
    </section>
    <div className="ux2-collection-tabs" role="group" aria-label="候选来源筛选">{[['all','全部',ids.length],['report','报告候选',nominatedAvailable.length],['saved','我的收藏',saved.length]].map(([key,text,count])=><button key={key} aria-pressed={source===key} onClick={()=>update({collection:String(key)})}>{text}<span>{count}</span></button>)}</div>
    {rawNominations===null?<p className="sp-error" role="status">报告候选名单暂不可读取，收藏仍保留。请查看原报告。</p>:null}
    {nominated.length>nominatedAvailable.length?<p className="sp-muted">报告中另有 {nominated.length-nominatedAvailable.length} 件商品资料暂不可读取，未加入比较。</p>:null}
    {[...new Set(data.favorites)].length>saved.length?<p className="sp-muted">部分收藏商品的资料暂不可读取，收藏记录仍保留。</p>:null}
    <div className="ux2-decision-cards">
      {visible.map(item=><article className={`ux2-decision-card${compare.includes(item.card.listing_id)?' is-selected':''}`} key={item.card.listing_id}>
        <div className="ux2-card-top">{badges(item)}<label className="ux2-pick"><input type="checkbox" aria-label={`对比 ${item.card.title}`} checked={compare.includes(item.card.listing_id)} disabled={!compare.includes(item.card.listing_id)&&compare.length>=comparisonLimit} onChange={()=>toggle(item.card.listing_id)}/>{compare.includes(item.card.listing_id)?'已选比较':'加入比较'}</label></div>
        <div className="ux2-candidate-identity"><button className="ux2-candidate-title" onClick={()=>select(item.card.listing_id)} title={item.card.title}><ProductThumbnail card={item.card}/><span><small>商品 #{item.card.listing_id}</small><strong>{item.card.title}</strong></span></button><div className="ux2-candidate-price"><b>{price(item.card)}</b><small>已保存挂牌价</small></div></div>
        <div className="ux2-decision-reason"><small>{basis(item)}</small><p>{item.reason}</p></div>
        {item.assessment?.conclusion==='not_met'?<p className="ux2-warning" data-tone={item.risks.length?'negative':'caution'}>逐项判断为“不建议”，报告提名不抵消这一风险。</p>:null}
        <div className="ux2-evidence-columns"><section><h3>已有依据支持</h3><DecisionEvidence points={item.supports} empty="暂无可确认的优势依据"/></section><section><h3>风险与冲突</h3><DecisionEvidence points={item.risks} empty="尚未列出，不代表没有风险"/></section></div>
        <section className="ux2-card-unknowns"><h3>购买前待核实</h3><DecisionEvidence points={item.unknowns} empty={item.assessment?'仍需结合实物和交易条件核对':'缺少逐项研究，不能仅凭标题或价格作判断'}/></section>
        <div className="ux2-card-footer"><button onClick={()=>select(item.card.listing_id)}>查看商品与证据 <ArrowRight size={14}/></button><button onClick={()=>ask(item)}>准备追问</button><button aria-label={`${item.saved?'取消收藏':'收藏'}商品 #${item.card.listing_id}`} disabled={saving!==undefined} onClick={()=>void favorite(item)}><Bookmark size={14} fill={item.saved?'currentColor':'none'}/>{saving===item.card.listing_id?'保存中…':item.saved?'已收藏':'收藏'}</button></div>
        <details className="sp-copy-help"><summary>完整判断与来源</summary><p>AI 判断不是独立核验；每条依据的来源见下方。{item.basis==='report'?'以下保留报告当时的判断。':''}</p>{item.assessment?<ConditionJudgments assessment={item.assessment} criteria={item.criteria}/>:null}<MarketReferenceSummary reference={data.market?.references[String(item.card.listing_id)]} select={select} compact/><Link to={contextual(marketHref(data.project.id,item.card.listing_id))}>查看行情参考 →</Link><button onClick={()=>select(item.card.listing_id)}>查看逐图证据</button></details>
      </article>)}
    </div>
    {!visible.length?<Panel className="ux2-shortlist-empty"><Bookmark size={28}/><h2>{source==='saved'?'还没有收藏商品':source==='report'?'暂无可查看的报告候选':'先留下几件值得比较的商品'}</h2><p>{source==='report'?'完成研究后，报告提及的候选会出现在这里。':'在全部商品中收藏感兴趣的商品，或等待研究形成候选。收藏不代表 AI 推荐。'}</p><Link to={contextual(`/projects/${data.project.id}?view=products`)}>浏览全部商品 →</Link></Panel>:null}
    {compare.length ? <section className="ux2-comparison" ref={comparison} aria-label="候选结构化比较">
      <div className="sp-between"><div><p className="sp-eyebrow">相同维度，看清取舍</p><h2>并排比较{compare.length?` · ${compare.length} 件`:''}</h2></div>{compare.length?<button onClick={()=>setCompare([])}>清空选择</button>:null}</div>
      {compare.length>comparisonLimit?<p className="sp-error" role="alert">最多并排比较 {comparisonLimit} 件，请先移出部分商品。</p>:null}
      {!compare.length?<p className="ux2-unknown">勾选 2–4 件商品，比较价格、研究依据、风险与未知项。不会自动调用 AI。</p>:null}
      {compare.length===1?<p className="ux2-unknown">再选一件，即可比较取舍。</p>:null}
      {selected.length>0&&selected.length<=comparisonLimit?<><p className="ux2-scroll-hint">左右滑动查看各件商品；未知项不参与推断或排名。</p><div className="ux2-compare-scroll" tabIndex={0} role="region" aria-label="横向商品比较表"><table className="ux2-compare-table"><thead><tr><th scope="col">比较维度</th>{selected.map(item=><th scope="col" key={item.card.listing_id}><button className="ux2-compare-remove" aria-label={`移出商品 #${item.card.listing_id}`} onClick={()=>toggle(item.card.listing_id)}><X size={14}/></button><ProductThumbnail card={item.card}/><button className="sp-title-button" title={item.card.title} onClick={()=>select(item.card.listing_id)}>{item.card.title}</button>{badges(item)}</th>)}</tr></thead><tbody>
        <tr><th scope="row">挂牌价</th>{selected.map(i=><td key={i.card.listing_id}><b className="ux2-price">{price(i.card)}</b></td>)}</tr>
        <tr><th scope="row">研究依据</th>{selected.map(i=><td key={i.card.listing_id}><small>{basis(i)}</small><p>{i.reason}</p></td>)}</tr>
        <tr><th scope="row">支持条件</th>{selected.map(i=><td key={i.card.listing_id}><DecisionEvidence points={i.supports} empty="未知，暂无有效支持依据"/></td>)}</tr>
        <tr><th scope="row">风险与冲突</th>{selected.map(i=><td key={i.card.listing_id}><DecisionEvidence points={i.risks} empty="未列出，不等于没有风险"/></td>)}</tr>
        <tr><th scope="row">待核实</th>{selected.map(i=><td key={i.card.listing_id}><DecisionEvidence points={i.unknowns} empty="仍需核对实物及交易条件"/></td>)}</tr>
        <tr><th scope="row">卖家自述成色</th>{selected.map(i=><td key={i.card.listing_id}>{i.card.search_condition||'未知'}</td>)}</tr>
        <tr><th scope="row">图片观察</th>{selected.map(i=><td key={i.card.listing_id}><VisualSummary taskId={data.project.id} listingId={i.card.listing_id} select={select} comparison compact/></td>)}</tr>
        <tr><th scope="row">卖家 / 地区</th>{selected.map(i=><td key={i.card.listing_id}>{i.card.seller_name||'卖家未知'}<p>{i.card.location||'地区未知'}</p></td>)}</tr>
        <tr><th scope="row">下一步</th>{selected.map(i=><td key={i.card.listing_id}><button onClick={()=>select(i.card.listing_id)}>查看商品与证据</button><button onClick={()=>ask(i)}>准备追问</button></td>)}</tr>
      </tbody></table></div></>:null}
    </section> : null}
    {compare.length ? <div className="ux2-comparison-tray" aria-label="已选比较商品"><div><Columns3 size={19}/><strong>{compare.length?`已选 ${compare.length} / ${comparisonLimit} 件`:'选择商品，比较取舍'}</strong><span>只比较，不改变收藏或排序</span></div>{selected.length?<div className="ux2-selected-chips">{selected.map(i=><button key={i.card.listing_id} onClick={()=>toggle(i.card.listing_id)} title={i.card.title}>#{i.card.listing_id}<X size={12}/></button>)}</div>:null}<div className="sp-actions"><button disabled={!compare.length||compare.length>comparisonLimit} onClick={()=>comparison.current?.scrollIntoView({block:'start',behavior:'smooth'})}>查看比较 <Check size={14}/></button><button className="sp-primary" disabled={compare.length<2||compare.length>comparisonLimit} onClick={aiCompare}><Sparkles size={14}/> 向 Agent 提问</button></div></div> : null}
  </div>;
}
