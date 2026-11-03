import type { ProjectOverview } from "../../api/projectClient";
import type { CriterionJudgment } from "../../api/types";
import { productInsights } from "./productInsights";
import { overviewReport, reportCandidateIds } from "./overviewReport";
import { evidenceText } from "../inspector/evidencePresentation";

export interface DecisionPoint { judgment: CriterionJudgment; label: string; priority?: 'hard'|'soft' }
/** Existing evidence only: nomination, price and seller copy are not advantages. */
export function decisionCandidates(data: ProjectOverview, sourceReady: boolean) {
  const insights=productInsights(data,sourceReady), report=overviewReport(data);
  const nominated=new Set(reportCandidateIds(data.report)??[]), saved=new Set(data.favorites);
  return new Map(data.cards.map(card=>{
    const insight=insights.items.get(card.listing_id);
    const current=insight?.assessment;
    const historical=nominated.has(card.listing_id)?report.study?.result?.research?.assessments.find(a=>a.listing_id===card.listing_id):undefined;
    const assessment=current??historical;
    const criteria=current?insight?.criteria:report.study?.result?.research?.criteria;
    const points=(assessment?.judgments??[]).map(judgment=>{const criterion=criteria?.find(c=>c.criterion_id===judgment.criterion_id);return {judgment,label:criterion?.description??judgment.criterion_id,priority:criterion?.priority}});
    return [card.listing_id,{card,insight,assessment,criteria,nominated:nominated.has(card.listing_id),saved:saved.has(card.listing_id),
      basis:current?'current' as const:historical?'report' as const:'none' as const,
      reason:evidenceText(assessment?.summary)??(nominated.has(card.listing_id)?"报告列为候选，但未提供可用的逐项推荐理由。":"已收藏，尚无可用的逐项研究。"),
      supports:points.filter(p=>p.judgment.status==='MET'&&p.judgment.evidence_refs.length>0),
      risks:points.filter(p=>['NOT_MET','CONFLICT'].includes(p.judgment.status)&&p.judgment.evidence_refs.length>0),
      unknowns:points.filter(p=>p.judgment.status==='UNKNOWN'||!p.judgment.evidence_refs.length),
    }] as const;
  }));
}
export type DecisionCandidate=ReturnType<typeof decisionCandidates> extends Map<number,infer T>?T:never;
export const comparisonLimit=4;
export function comparisonIds(value:string|null,data:ProjectOverview) {
  return [...new Set((value??'').split(',').filter(s=>/^[1-9]\d*$/.test(s)).map(Number))]
    .filter(id=>Number.isSafeInteger(id)&&data.cards.some(card=>card.listing_id===id));
}
