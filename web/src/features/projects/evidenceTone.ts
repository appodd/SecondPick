import type { CriterionJudgment } from "../../api/types";
import type { SemanticTone } from "../../components/status/ExecutionStatus";
import type { ProductInsight } from "./productInsights";

/** Display only. Never changes a judgment or implies independent verification. */
export function judgmentTone(j:CriterionJudgment,priority?:'hard'|'soft'):SemanticTone {
  if(j.status==='NOT_MET'||j.status==='CONFLICT')return j.evidence_refs.length?'negative':'caution';
  // Lack of verification alone is not an attention signal. Use explicit hard
  // buying criteria, never a free-text guess about which claim matters.
  if(j.status==='UNKNOWN')return priority==='hard'?'caution':'neutral';
  if(j.source_type==='platform_display')return j.evidence_refs.length?'positive':'caution';
  // Seller copy, supplements, inference and image claims retain provenance,
  // without coloring every unverified description amber.
  return 'neutral';
}
export function matchTone(insight:ProductInsight):SemanticTone {
  return insight.match==='meets'?'positive':insight.match==='outside'?'negative':insight.match==='unknown'?'caution':'neutral';
}
export function researchTone(insight:ProductInsight):SemanticTone {
  if(!insight.assessment)return 'neutral';
  if(insight.ai==='conditional'||insight.ai==='insufficient_evidence')return 'caution';
  if(insight.ai==='not_met')return insight.assessment.judgments.some(j=>j.evidence_refs.length>0&&['NOT_MET','CONFLICT'].includes(j.status))?'negative':'caution';
  return insight.assessment.judgments.some(j=>judgmentTone(j,insight.criteria?.find(c=>c.criterion_id===j.criterion_id)?.priority)==='positive')?'positive':'neutral';
}
