import { useGoalContinuity } from "./GoalContinuity";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { monitorApi } from "../../api/monitorClient";
import { Link } from "react-router-dom";
import { marketHref } from "../market/marketAnalysis";
import { useContextHref } from "./contextNavigation";
import { useProjectAgent } from "./ProjectAgent";
import { defaultAgentScope } from "./agentContext";
import { ArrowUpRight, Sparkles, ArrowRight, CircleHelp } from "lucide-react";
import { projectApi, type ProjectOverview, type Report } from "../../api/projectClient";
import { Panel, date, price, ProductThumbnail } from "./projectUi";
import { OverviewRuntime } from "./OverviewRuntime";
import { EvidenceChanges } from "./EvidenceChanges";
import { ConditionJudgments } from "../conversation/ConditionJudgments";
import { MarketReferenceSummary } from "../market/MarketReferenceSummary";
import { overviewReport, reportOpening } from "./overviewReport";
import { overviewJourney } from "./overviewJourney";
import { FullResearchReport } from "./FullResearchReport";
import { ReportScopeSummary } from "./ReportScopeSummary";
import { evidenceText } from "../inspector/evidencePresentation";
import { VisualSummary } from "../inspector/VisualSummary";
import { VisualInvestigation } from "../inspector/VisualInvestigation";
import { ProjectGuide, projectGuide } from "./ProjectGuide";
import { ProjectGoalCard } from './ProjectGoalCard';
import "./overview.css";

export function Overview({ data, go, select, busy, action }: {
  data: ProjectOverview; go: (view: string) => void; select: (id: number) => void; busy: boolean;
  action: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [changes] = useState(data.changes);
  const [reading, setReading] = useState<Report | null>(null);
  const [visualOpen, setVisualOpen] = useState(false);
  const summary = overviewReport(data), report = data.report, baseJourney = overviewJourney(data);
  const contextual = useContextHref(data.project.id), agent = useProjectAgent();
  const continuity = useGoalContinuity(), goalState = continuity.state;
  const unresolvedGoal = !data.project.goal.trim() || !continuity.loading && (goalState === "unknown" || goalState === "unlinked");
  const needsGoalSetup = !report && unresolvedGoal && !["running", "queued", "completed"].includes(baseJourney.kind);
  const monitors = useQuery({queryKey:['monitors',data.project.id],queryFn:()=>monitorApi.list(data.project.id),enabled:!report,retry:false,refetchInterval:report?false:5000});
  const journey = needsGoalSetup ? { ...baseJourney, kind: "goal", title: "先确认你的选购目标", description: "当前目标尚未明确或暂不可核对。先确认预算和关键条件，已有商品仍可浏览。", action: "核对选购目标", step: 0 } : report ? baseJourney : projectGuide(data,monitors.isError?undefined:monitors.data);
  const unlinked = goalState === "unlinked" || !!report && data.goal_context?.report_current === false;
  const evidenceChanged = report?.evidence_current === false;
  const historical = unlinked || evidenceChanged || goalState === "unknown";
  const ask = () => agent.open(defaultAgentScope(data, !report && !data.total ? "monitors" : "overview"));
  return <div className="sp-overview">
    <ProjectGuide key={data.project.id} data={data} go={go}/>
    <ProjectGoalCard key={data.project.id} data={data}/>
    <Panel variant="emphasis" className={`sp-report sp-current-report sp-overview-hero${historical ? " sp-report-historical" : ""}`}>
      <div className="sp-between"><p className="sp-eyebrow"><Sparkles size={16} />{report ? historical ? "已保存的研究判断 · 适用范围待核对" : "你的选购判断" : "开始你的选购研究"}</p>
        <span className={`sp-journey-tag sp-journey-${journey.kind}`}>{journey.kind === "running" ? "研究进行中" : journey.kind === "paused" ? "研究暂停" : journey.kind === "completed" ? "项目已结束" : journey.kind === "goal" ? data.policy.paused ? "目标待确认 · 研究已暂停" : "目标待确认" : report ? "已有研究报告" : "尚无研究报告"}</span></div>
      {report ? <>
        <h2 className="sp-overview-hero-label">{historical ? "先核对变化，再参考这份结论" : "目前，应该怎样选？"}</h2>
        {!summary.conclusion && reportOpening(report.content) ? <small className="sp-muted">报告开篇原文</small> : null}
        <p className="sp-overview-conclusion">{summary.conclusion ?? reportOpening(report.content) ?? "已有研究报告，打开全文查看本轮判断。"}</p>
        {historical ? <p className="sp-overview-caution">{evidenceChanged ? "商品证据已有更新，本结论仍基于原快照。" : unlinked ? "报告尚未与当前目标完成衔接，候选仅作历史参考。" : "目标适用性暂不可确认，保留原报告供核对。"}</p> : null}
        <p className="sp-overview-meta">报告 #{report.id} · {date(report.created_at)} · {summary.study ? `本轮 ${summary.study.listing_ids.length} 件商品` : "本轮范围待确认"}{report.limited ? " · 有限样本研究" : ""}</p>
        <div className="sp-actions"><button className="sp-primary" onClick={ask}><Sparkles size={15} /> 带着结论继续问</button><button onClick={() => setReading({ ...report })}>阅读完整报告 <ArrowUpRight size={14} /></button></div>
        <details className="sp-overview-disclosure"><summary>这份结论的依据与适用范围</summary><ReportScopeSummary data={data}/><p className="sp-muted">{summary.conclusion ? "结论直接引用报告中的完整结论句。" : reportOpening(report.content) ? "上方保留完整开篇段落，不将有限样本扩展为全市场结论。" : "未提供独立短结论，不从长文截取片段或生成新的综合推荐。"}候选旁的价格是当前已保存挂牌价；原文价格以当时输入为准。</p><p className="sp-muted">{data.pending} 件当前版本未纳入报告，不等于应调用 AI 的数量。</p><button onClick={() => go("research")}>查看覆盖与历史报告 →</button></details>
      </> : <>
        <h2 className="sp-overview-welcome">{journey.title}</h2><p className="sp-overview-intro">{journey.description}</p>
        <div className="sp-actions">{needsGoalSetup ? <Link className="sp-primary" to={contextual(`/projects/${data.project.id}?view=overview&editGoal=1`)}>{journey.action}<ArrowRight size={15}/></Link> : <button className="sp-primary" onClick={() => go(journey.view)}>{journey.action}<ArrowRight size={15}/></button>}{data.total ? journey.view!=="products" ? <button onClick={() => go("products")}>先浏览 {data.total} 件商品</button> : null : !needsGoalSetup ? <button className="sp-overview-agent-link" onClick={ask}>和 Agent 梳理采集计划</button> : null}</div>
      </>}
    </Panel>
    <details className="sp-secondary-details"><summary>证据变化与待复评</summary><EvidenceChanges data={data} compact /></details>
    <div className="sp-overview-grid">
      <div className="sp-overview-main">
        <Panel className="sp-overview-picks"><div className="sp-between"><div><p className="sp-eyebrow">少量重点，逐件核对</p><h2>{historical ? "报告提及的候选" : "值得先看的商品"}</h2></div><button className="sp-status-link" onClick={() => go("shortlist")}>候选清单 <ArrowUpRight size={14}/></button></div>
          {summary.candidates.map(({ id, card, assessment }, index) => <article className="sp-overview-candidate" key={id}>
            <div className="sp-candidate-lead">{card ? <button onClick={() => select(id)} className="sp-overview-product"><ProductThumbnail card={card}/><span><small>报告候选 {String(index + 1).padStart(2, "0")} · #{id}</small><strong>{card.title}</strong></span></button> : <p>候选 #{id} · 当前商品资料暂不可读取</p>}{card ? <b>{price(card)}</b> : null}</div>
            <OverviewExcerpt text={evidenceText(assessment?.summary) ?? "报告提及此商品，尚无可归属的逐项推荐理由；请核对原文与商品证据。"}/>
            {assessment?.conclusion === "not_met" ? <p className="sp-overview-caution">候选名单与本批“不符合要求”的判断不一致，请核对原报告。</p> : null}
            <div className="sp-candidate-source"><small>{historical ? "历史判断，需核对当前适用性" : "报告中的候选，不代表已完成验货"}</small>{card ? <button onClick={() => select(id)}>查看商品与证据 <ArrowRight size={14}/></button> : null}</div>
            {card ? <details className="sp-overview-disclosure"><summary>逐项判断与价格依据</summary><MarketReferenceSummary reference={data.market?.references[String(id)]} select={select} compact/>{assessment ? <ConditionJudgments assessment={assessment} criteria={summary.study?.result?.research?.criteria}/> : <p className="sp-muted">本批没有有效逐项判断。</p>}</details> : null}
          </article>)}
          {!summary.candidates.length ? <div className="sp-overview-empty"><CircleHelp size={26}/><h3>{report ? summary.ids === null ? "候选名单暂不可读取" : "本轮没有列出推荐候选" : "还没有研究候选"}</h3><p>{report ? "这不代表所有商品都不合适。可以阅读报告，或先浏览已收集的商品。" : "先积累样本，再由研究结果筛出值得核对的商品。收藏与 AI 推荐各自保留。"}</p><button onClick={() => go("products")}>浏览全部商品{data.total ? `（${data.total}）` : ""}</button></div> : null}
          {(summary.ids?.length ?? 0) > 3 ? <p className="sp-muted">展示报告名单前 3 件，共 {summary.ids!.length} 件；顺序不代表综合评分排名。</p> : null}
        </Panel>
        {summary.concerns.length ? <Panel className="sp-overview-concerns"><div className="sp-between"><h2>下单前，先问清这些</h2><span className="sp-journey-tag">待核实</span></div><ul>{summary.concerns.slice(0, 3).map((item, index) => <li key={`${item.listingId}:${item.criterion_id}:${index}`}><button onClick={() => select(item.listingId)}>商品 #{item.listingId}</button><span className="sp-concern-kind">{item.status === "CONFLICT" ? "证据冲突" : item.status === "UNKNOWN" ? "信息不足" : "与要求不符"}</span><OverviewExcerpt text={item.reason}/></li>)}</ul><p className="sp-muted">来自本报告批次的逐项判断；信息缺失不等于不合格，也不代表已覆盖所有风险。</p></Panel> : null}
      </div>
      <aside className="sp-overview-aside" aria-label="下一步与重要变化">
        {report ? <Panel className="sp-overview-next"><p className="sp-eyebrow">接下来</p><h2>{journey.title}</h2><p>{journey.description}</p><button className="sp-primary" onClick={() => go(journey.view)}>{journey.action}<ArrowRight size={15}/></button><div className="sp-overview-shortcuts"><button onClick={() => go("products")}>全部商品 <span>{data.total}</span></button><button onClick={() => go("monitors")}>监控任务 <ArrowUpRight size={13}/></button><Link to={contextual(marketHref(data.project.id))}>查看挂牌行情 <ArrowUpRight size={13}/></Link></div></Panel> : null}
        <Panel className="sp-overview-changes"><div className="sp-between"><h2>重要变化</h2>{changes.length ? <span className="sp-journey-tag">{changes.length} 条</span> : null}</div>{changes.length ? <ul>{changes.slice(0, 3).map(change => <li key={change.id}><p>{change.content}</p><small>{date(change.created_at)}</small><button onClick={() => go("research")}>查看依据 →</button></li>)}</ul> : <p className="sp-muted">{report ? "自上次确认阅读后，没有新的报告变更。" : "首份研究报告完成后，这里会保留重要变化。"}</p>}{report && changes.length ? <button disabled={busy} onClick={() => action(() => projectApi.read(data.project.id, report.id))}>标为已查看</button> : null}</Panel>
      </aside>
    </div>
    <details className="sp-overview-more"><summary>运行详情 <span>监控、研究任务与覆盖范围</span></summary><OverviewRuntime data={data} go={go}/></details>
    <details className="sp-overview-more" onToggle={event => setVisualOpen(event.currentTarget.open)}><summary>图片证据与视觉调查 <span>按需查看，不会自动分析图片</span></summary>{visualOpen ? <Panel><p className="sp-muted">图片已缓存不代表 AI 已查看；AI 观察也不是独立核验。以下仅查看重点候选或收藏前 3 件，不重写已保存报告。</p><VisualInvestigation taskId={data.project.id} select={select}/>{(summary.candidates.length ? summary.candidates.map(c => c.id) : data.favorites).slice(0, 3).map(id => <VisualSummary key={id} taskId={data.project.id} listingId={id} select={select}/>)}{!summary.candidates.length && !data.favorites.length ? <p>暂无明确重点范围，可在商品详情查看已有图片证据。</p> : null}</Panel> : null}</details>
    {reading ? <FullResearchReport report={reading} latest={report} close={() => setReading(null)} readLatest={() => { if (report) setReading({ ...report }); }}/> : null}
  </div>;
}

function OverviewExcerpt({ text }: { text: string }) {
  return text.length > 180 ? <details className="sp-overview-excerpt"><summary><span>{text}</span><small>展开原文</small></summary></details> : <p className="sp-overview-reason">{text}</p>;
}
