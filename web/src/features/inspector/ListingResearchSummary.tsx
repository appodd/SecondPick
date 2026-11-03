import type { AssessmentBatch, ListingEvidence, TaskDetail } from "../../api/types";
import type { ProjectOverview } from "../../api/projectClient";
import { StatusBadge } from "../../components/status/ExecutionStatus";
import { productResearchStatus, studyStatus } from "../../components/status/statusModel";
import { applyCurrentInputs } from "../conversation/researchValidity";
import { EvidenceExcerpt } from "../conversation/StructuredAssessment";
import { evidenceText } from "./evidencePresentation";
import { judgmentBasis, matchStatusLabels } from "../conversation/matchEvidence";

const conclusionLabels = { consider: "可考虑", conditional: "有条件考虑", not_met: "不符合当前要求", insufficient_evidence: "证据不足，暂不能判断" };

export function ListingResearchSummary({ evidence, project, task }: { evidence: ListingEvidence; project?: ProjectOverview; task?: TaskDetail }) {
  const listing = evidence.listing_id;
  const card = project?.cards.find(value => value.listing_id === listing);
  const studies = project?.studies.filter(value => !value.kind.startsWith("seller:") && value.listing_ids.includes(listing)).sort((a, b) => b.id - a.id) ?? [];
  const currentStudies = project?.goal_context ? studies.filter(value => value.goal_revision === project.goal_context!.current_revision) : studies;
  const currentResult = currentStudies.find(value => value.state === "completed" && (!value.current_listing_ids || value.current_listing_ids.includes(listing)) && value.result?.research?.assessments.some(item => item.listing_id === listing));
  const active = currentStudies.find(value => ["running", "queued"].includes(value.state));
  const study = currentResult ?? studies.find(value => value.state === "completed" && value.result?.research?.assessments.some(item => item.listing_id === listing)) ?? studies.find(value => value.state === "completed");
  const revision = task?.preference_revision_id ?? Math.max(0, ...(task?.preference_revisions.map(value => value.id) ?? []));
  const batch = applyCurrentInputs(task?.research?.assessment_batches ?? [], revision, task?.research?.page?.evidence_signature)
    .filter(value => value.result.assessments.some(item => item.listing_id === listing)).sort((a, b) => b.id - a.id)[0];
  const result = project ? study?.result?.research : batch?.result;
  const assessment = result?.assessments.find(value => value.listing_id === listing);
  const stale = project?.goal_context && study ? study.goal_revision !== project.goal_context.current_revision || card?.research_state !== "evaluated" || !!study.current_listing_ids && !study.current_listing_ids.includes(listing) : !project && batch ? (batch.candidate_stale?.[String(listing)] ?? batch.stale) : undefined;
  const refs = project ? undefined : batch?.evidence_refs;
  let recommended = false;
  try { recommended = (JSON.parse(project?.report?.candidate_ids_json ?? "[]") as number[]).includes(listing); } catch { /* No reliable membership. */ }
  const snapshot = project ? study?.snapshot_at : batch?.created_at;
  const groups = [{ title: "选购依据", items: assessment?.judgments.filter(value => value.status === "MET") ?? [] },
    { title: "已发现的问题与冲突", items: assessment?.judgments.filter(value => ["NOT_MET", "CONFLICT"].includes(value.status)) ?? [] },
    { title: "仍待核实", items: assessment?.judgments.filter(value => value.status === "UNKNOWN") ?? [] }];
  return <section className="inspector-block le-ai" aria-label="AI 选购判断">
    <div className="le-section-heading"><h3>AI 选购判断</h3>{card ? <StatusBadge status={productResearchStatus(card.research_state)} /> : null}</div>
    {active ? <div className="le-active"><StatusBadge status={studyStatus(active)} live /><p>已保存的判断仍基于原快照，新一轮完成后再核对结论。</p></div> : null}
    {recommended ? <p className="le-recommendation">{project?.report?.evidence_current === false ? "原报告曾将此商品列为候选；候选证据已更新，综合建议尚未整合。" : project?.goal_context?.report_current === false ? "历史报告曾将此商品列为候选，尚未按当前目标校准。" : "当前项目报告将此商品列为 AI 候选。候选身份不等于已完成实物或卖家核验。"}</p> : null}
    {assessment ? <>
      <p className="le-conclusion"><strong>{stale ? "历史判断：" : ""}{stale && assessment.conclusion === "not_met" ? "不符合当时要求" : conclusionLabels[assessment.conclusion] ?? "已保存的研究判断"}</strong></p>
      {evidenceText(assessment.summary) ? <p className="message-content">{assessment.summary}</p> : null}
      {stale === true ? <p className="le-limit">历史判断：要求或商品证据已变化，不能直接作为当前结论。</p> : <p className="le-limit">{project ? project.goal_context ? "这是固定快照上的已保存判断；目标版本及商品证据是否适用需结合当前研究状态核对，不能当作实物核验。" : "这是固定快照上的已保存判断；当前要求与商品版本是否仍适用，接口尚未提供逐项校验。" : "判断的要求与证据仍适用，但卖家自述与 AI 推断不等于独立核实。"}</p>}
      {groups.filter(group => group.items.length).map(group => <div className="le-judgment-group" key={group.title}><h4>{group.title}</h4>
        <Judgments items={group.items.slice(0, 3)} criteria={result!.criteria} refs={refs} />
        {group.items.length > 3 ? <details><summary>查看其余 {group.items.length - 3} 项</summary><Judgments items={group.items.slice(3)} criteria={result!.criteria} refs={refs} /></details> : null}</div>)}
    </> : <div className="le-empty">
      <p>尚无本商品可展示的逐项研究结论。</p>
      <p>{card?.research_state === "summarized" ? "此商品曾纳入批次概述，尚不能据此当作深入调查已完成。" : "目前不能确认关键要求是否满足；信息缺失不等于不合格。"}</p>
      {recommended ? <p>报告未提供可单独归属本商品的结构化推荐理由，请结合完整报告与原始证据核实。</p> : null}
      {study?.listing_ids.length === 1 && evidenceText(study.result?.content) ? <details><summary>查看该商品已保存的文字研究</summary><p className="message-content">{study.result!.content}</p><p className="muted">文字研究未提供逐项证据关联，不能将其中的推断当作核实事实。</p></details> : null}
    </div>}
    {snapshot ? <p className="muted">{project ? "研究输入快照" : "评估保存于"}：{new Date(snapshot).toLocaleString("zh-CN")}</p> : null}
    <p className="muted">仅检查最近已返回的研究记录{project ? "（最多30次）" : ""}；未显示不代表历史上从未研究。未列出问题也不等于没有风险。</p>
    {project?.report && recommended ? <details><summary>查看项目报告上下文</summary><p className="muted">完整报告可能讨论多件商品，不作为本商品专属结论。</p><p className="message-content">{project.report.content}</p></details> : null}
  </section>;
}

function Judgments({ items, criteria, refs }: { items: AssessmentBatch["result"]["assessments"][number]["judgments"]; criteria: AssessmentBatch["result"]["criteria"]; refs?: Record<string, unknown> }) {
  return <ul className="le-judgments">{items.map(item => <li key={item.criterion_id}>
    <strong>{criteria.find(value => value.criterion_id === item.criterion_id)?.description ?? "研究要求"}</strong>
    <span className="le-source">{matchStatusLabels[item.status]} · {judgmentBasis(item)}</span>
    {evidenceText(item.reason) ? <p>{item.reason}</p> : null}
    {item.evidence_refs.length ? <details><summary>查看引用依据（{item.evidence_refs.length}）</summary>
      {refs ? item.evidence_refs.map(ref => <EvidenceExcerpt key={ref} value={refs[ref]} />) : <><p className="muted">已有接口返回引用编号，尚未返回对应输入原文；请同时核对下方商品证据，不能把编号视为独立核验。</p><p>{item.evidence_refs.join("、")}</p></>}
    </details> : null}
  </li>)}</ul>;
}
