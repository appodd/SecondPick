import type { ProjectCard, ProjectOverview } from "../../api/projectClient";
import { StatusBadge } from "../../components/status/ExecutionStatus";
import { productResearchStatus } from "../../components/status/statusModel";
import { aiLabels, matchLabels, type MatchKind, type ProductInsight, type ProductInsights } from "./productInsights";
import { ConditionJudgments } from "../conversation/ConditionJudgments";
import { matchTone, researchTone } from "./evidenceTone";

export function ConditionCell({ insight }: { insight: ProductInsight }) {
  return <div className="sp-product-insight" title={insight.detail}><StatusBadge status={insight.status} tone={matchTone(insight)} /><small>{insight.reason}</small></div>;
}

export function ResearchCell({ card, insight, compact=false }: { card: ProjectCard; insight: ProductInsight; compact?:boolean }) {
  if(compact)return <div className="sp-product-insight ux2-research-cell" title={insight.aiDetail}>{insight.assessment?<><StatusBadge tone={researchTone(insight)} status={{kind:insight.ai==='not_met'?'attention':insight.ai==='insufficient_evidence'?'unknown':'ready',label:aiLabels[insight.ai]}}/>{insight.candidate?<small>报告候选 · 已逐项分析</small>:<small>已逐项分析 · 实物待核实</small>}</>:insight.candidate?<><StatusBadge tone="neutral" status={{kind:'ready',label:'报告候选'}}/><small>尚无可展示的逐项判断</small></>:<StatusBadge tone="neutral" status={productResearchStatus(card.research_state)}/>}</div>;
  return <div className="sp-product-insight" title={insight.aiDetail}>
    {insight.candidate ? <StatusBadge tone="neutral" status={{ kind: "ready", label: "报告重点候选", reason: insight.aiDetail }} /> : null}
    {insight.assessment ? <><StatusBadge tone={researchTone(insight)} status={{ kind: insight.ai === "not_met" ? "attention" : insight.ai === "insufficient_evidence" ? "unknown" : "ready", label: aiLabels[insight.ai], reason: insight.aiDetail }} /><small className="sp-ai-excerpt">{insight.assessment.summary}</small></> : null}
    <StatusBadge tone="neutral" status={productResearchStatus(card.research_state)} />
    {insight.assessment ? <ConditionJudgments assessment={insight.assessment} criteria={insight.criteria} /> : null}
    {!insight.assessment && card.research_state === "evaluated" ? <small>具体判断请查看商品详情</small> : null}
  </div>;
}

export function ProductOverviewStats({ data, insights, results, params, update }: { data: ProjectOverview; insights: ProductInsights; results: number; params: URLSearchParams; update: (values: Record<string, string>) => void }) {
  const kinds: MatchKind[] = ["meets", "outside", "unknown", "unjudged"];
  return <section className="sp-product-summary" aria-label="项目商品概况">
    <div className="sp-product-stats">
      <button onClick={() => update({ q: "", state: "all", match: "all", ai: "all", page: "0" })} title="全项目已收录商品，按商品ID去重；点击清除筛选">已收录 <strong>{insights.total}</strong></button>
      {kinds.filter(kind => kind !== "unjudged" || insights.counts.unjudged > 0).map(kind => <button key={kind} aria-pressed={params.get("match") === kind} title={`${matchLabels[kind]}：全项目按当前目标已知字段初筛，与其他条件分类互斥；不表示实物已核验。点击结合现有搜索筛选。`} onClick={() => update({ match: params.get("match") === kind ? "all" : kind, ai: "all", page: "0" })}>{matchLabels[kind]} <strong>{insights.counts[kind]}</strong></button>)}
      <button aria-pressed={params.get("ai") === "candidate"} disabled={!!data.report && !insights.reportConfirmed || insights.version === null} title="仅统计目标版本已核对的当前报告明确候选；独立于条件分类，不能相加。不是全项目逐项研究完成数量。" onClick={() => update({ ai: params.get("ai") === "candidate" ? "all" : "candidate", match: "all", page: "0" })}>AI 报告候选 <strong>{!!data.report && !insights.reportConfirmed || insights.version === null ? "—" : insights.candidateCount}</strong></button>
      <span className="sp-filter-count" role="status">当前筛选 {results} 件</span>
    </div>
    {!insights.version ? <p className="sp-muted" role="status">目标待确认，历史判断暂作参考。</p> : null}
    <details className="sp-copy-help"><summary>筛选与数据来源</summary><p>{insights.version ? `按目标 v${insights.version} 初筛，初步符合不等于已核验。` : "目标版本待确认，暂不沿用历史判断。"}条件分类互斥；AI 报告候选独立计数。标题与挂牌价可能仅为卖家自述。</p></details>
  </section>;
}
