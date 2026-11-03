import type { ProjectCard, ProjectOverview } from "../../api/projectClient";
import type { AssessmentBatch } from "../../api/types";
import type { StatusValue } from "../../components/status/statusModel";
import { initialGoalProposal } from "./goalImpact";
import { productConditions } from "./productConditions";
import { candidateIds } from "./reportCandidates";
import { assessmentBasis } from "../conversation/matchEvidence";

export type MatchKind = "meets" | "outside" | "unknown" | "unjudged";
export const matchLabels: Record<MatchKind, string> = { meets: "初步符合", outside: "明确不符合", unknown: "待核实", unjudged: "尚未判断" };
export const aiLabels = { candidate: "报告重点候选", consider: "可考虑", conditional: "有条件考虑", not_met: "不建议", insufficient_evidence: "证据不足", unresearched: "待逐项研究" };
export type AiKind = keyof typeof aiLabels;
type Assessment = AssessmentBatch["result"]["assessments"][number];
export interface ProductInsight {
  match: MatchKind; reason: string; detail: string; status: StatusValue;
  candidate: boolean; assessment?: Assessment; criteria?: AssessmentBatch["result"]["criteria"]; ai: AiKind; aiDetail: string;
}
export interface ProductInsights {
  items: Map<number, ProductInsight>; total: number; counts: Record<MatchKind, number>;
  candidateCount: number; version: number | null; reportConfirmed: boolean;
}

/** Read-only projection. Coverage and report membership are never substituted for a judgment. */
export function productInsights(data: ProjectOverview, sourceReady = true): ProductInsights {
  const context = data.goal_context;
  const policyKnown = Array.isArray(data.policy.hard) && data.policy.budget !== undefined && typeof data.project?.goal === "string";
  const version = sourceReady && policyKnown && context && !context.legacy_unmerged && Number.isSafeInteger(context.current_revision) && context.current_revision > 0 ? context.current_revision : null;
  const reportConfirmed = version !== null && context?.report_current === true && data.report?.goal_revision === version && data.report?.evidence_current !== false;
  const candidates = new Set(reportConfirmed ? candidateIds(data) : []);
  const assessments = new Map<number, Assessment>();
  const criteria = new Map<number, AssessmentBatch["result"]["criteria"]>();
  for (const study of [...(data.studies ?? [])].sort((a, b) => b.id - a.id)) {
    if (version === null || study.goal_revision !== version || study.state !== "completed" || study.kind.startsWith("seller:")) continue;
    for (const item of study.result?.research?.assessments ?? []) {
      if (study.current_listing_ids && !study.current_listing_ids.includes(item.listing_id)) continue;
      if (!assessments.has(item.listing_id)) {
        assessments.set(item.listing_id, item);
        criteria.set(item.listing_id, study.result!.research!.criteria);
      }
    }
  }
  const proposal = policyKnown ? initialGoalProposal(data) : { goal: "", budget: null, minimumMemory: null, hard: [], soft: [] };
  const hasConditions = proposal.budget !== null || proposal.hard.some(value => value.trim());
  const counts: Record<MatchKind, number> = { meets: 0, outside: 0, unknown: 0, unjudged: 0 };
  const items = new Map<number, ProductInsight>();
  for (const impact of productConditions(data.cards, proposal)) {
    const { card } = impact;
    const match: MatchKind = version === null || !hasConditions ? "unjudged" : impact.kind === "meets_known" ? "meets" : impact.kind;
    const detail = version === null ? "当前目标版本尚未确认，不沿用历史条件判断。" : !hasConditions ? "当前目标未设置可自动核对的硬条件；不从自由文本或软偏好猜测条件。" : `目标 v${version}：${impact.reasons.join("；")}。仅基于保存字段初筛，卖家自述不等于独立核实。`;
    const reason = match === "unjudged" ? (version === null ? "目标版本待确认" : "未设置可核对的硬条件")
      : impact.reasons.some(value => value.includes("超出")) ? "超过预算（已保存挂牌价）"
      : impact.reasons.some(value => value.includes("低于拟定")) ? "内存不足（标题自述）"
      : impact.reasons.some(value => value.startsWith("芯片不符")) ? "芯片不符（标题自述）"
      : impact.reasons.some(value => value.startsWith("机型不符")) ? "机型不符（标题自述）"
      : match === "meets" ? "已知字段初步符合，仍需核验"
      : impact.reasons.some(value => value.includes("内存缺失")) ? "内存信息待核实"
      : impact.reasons.some(value => value.includes("没有可用")) ? "挂牌价待核实"
      : proposal.hard.some(value => /原装|原厂|正品/.test(value)) ? "原装性等硬条件待核实" : "硬条件证据待核实";
    // Server coverage is projected against current goal + evidence signatures. If it
    // no longer says evaluated, an older item judgment cannot become a current one.
    const assessment = card.research_state === "evaluated" ? assessments.get(card.listing_id) : undefined;
    const candidate = candidates.has(card.listing_id);
    const ai: AiKind = assessment?.conclusion ?? (candidate ? "candidate" : "unresearched");
    const aiDetail = assessment ? `目标 v${version} 的已保存逐项判断：${assessment.summary}；依据类型：${assessmentBasis(assessment.judgments)}。不等于独立实物核验。`
      : candidate ? `目标 v${version} 的当前报告明确列为候选；候选身份不等于逐项分析或实物核验。`
      : version === null ? "目标版本未确认，历史判断不作为当前 AI 结论。"
      : card.research_state === "evaluated" ? "当前版本已逐项分析，但概览仅提供最近30次执行，未读到此商品的具体判断；可打开商品详情查看已有研究。"
      : "没有可展示的当前逐项判断；批次概述、排队或被规则排除均不代表 AI 推荐。";
    counts[match]++;
    items.set(card.listing_id, { match, reason, detail, status: { kind: match === "meets" ? "ready" : match === "outside" ? "attention" : "unknown", label: matchLabels[match], reason: detail }, candidate, assessment, criteria: criteria.get(card.listing_id), ai, aiDetail });
  }
  return { items, total: items.size, counts, candidateCount: [...items.values()].filter(item => item.candidate).length, version, reportConfirmed };
}

export function filterInsight(card: ProjectCard, insight: ProductInsight, params: URLSearchParams) {
  const match = params.get("match"), ai = params.get("ai");
  return (!match || match === "all" || insight.match === match) && (!ai || ai === "all" || (ai === "candidate" ? insight.candidate : ai === "unresearched" ? !insight.assessment && card.research_state !== "evaluated" : insight.assessment?.conclusion === ai));
}
