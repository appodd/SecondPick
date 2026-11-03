import type { AssessmentBatch } from "../../api/types";
import { assessmentBasis, judgmentBasis, matchStatusLabels } from "./matchEvidence";

export function ConditionJudgments({ assessment, criteria }: {
  assessment: AssessmentBatch["result"]["assessments"][number];
  criteria?: AssessmentBatch["result"]["criteria"];
}) {
  return <details className="sp-condition-judgments">
    <summary>条件匹配与证据 · {assessmentBasis(assessment.judgments)}</summary>
    <ul>{assessment.judgments.map(item => <li key={item.criterion_id}>
      <strong>{criteria?.find(c => c.criterion_id === item.criterion_id)?.description ?? item.criterion_id}</strong>
      ：{matchStatusLabels[item.status]} · {judgmentBasis(item)}
      <p>{item.reason}</p>
    </li>)}</ul>
    <p className="sp-muted">符合表示现有依据支持条件匹配，不等于已独立核验或建议立即购买。材料支持范围请查看具体判断与商品证据；图片链接不代表已查看图片。</p>
  </details>;
}
