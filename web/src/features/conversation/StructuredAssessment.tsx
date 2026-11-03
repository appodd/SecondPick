import type { AssessmentBatch } from "../../api/types";
import { matchStatusLabels as statuses, judgmentBasis } from "./matchEvidence";

const conclusions = { consider: "可考虑", conditional: "有条件考虑", not_met: "不符合要求", insufficient_evidence: "证据不足" };

export function StructuredAssessment({ batch, onSelectListing }: {
  batch: AssessmentBatch; onSelectListing: (id: number) => void;
}) {
  const staleCount = batch.candidate_stale ? Object.values(batch.candidate_stale).filter(Boolean).length :
    (batch.stale ? batch.result.assessments.length : 0);
  const partial = staleCount > 0 && staleCount < batch.result.assessments.length;
  return <details className="shortlist-full-analysis" open={!batch.stale && !batch.batch_index}>
    <summary>{partial ? "部分候选评估已过期" : batch.stale ? "历史逐项评估（要求或证据已变化）" : "已保存的逐项评估"}</summary>
    {batch.stale && <p className="muted">{partial ? `其中 ${staleCount} 件候选的要求或证据已变化，请按各商品标记查看。` : "这次判断依据旧输入，不能作为当前结论。"}</p>}
    <p className="muted">本次评估 {batch.result.assessments.length} 件候选，仅覆盖下列商品。符合项仍需区分卖家声明与独立核实。</p>
    <ul>{batch.result.criteria.map(criterion => <li key={criterion.criterion_id}>
      {criterion.priority === "hard" ? "硬性要求" : "偏好"}：{criterion.description}
      {criterion.source_refs?.includes("task_goal") && <span className="muted">（来源：原始任务目标）</span>}
      {criterion.source_refs?.some(ref => ref.startsWith("preference_revision:")) && <span className="muted">（来源：已保存需求修订）</span>}
    </li>)}</ul>
    {batch.result.assessments.map(candidate => <article key={candidate.listing_id}>
      <button onClick={() => onSelectListing(candidate.listing_id)}>查看商品 #{candidate.listing_id} 的证据</button>
      <p className="muted">{(batch.candidate_stale?.[String(candidate.listing_id)] ?? batch.stale) ?
        "历史判断：要求或该商品证据已变化" : "判断的要求与证据仍适用"}</p>
      <p><strong>{conclusions[candidate.conclusion]}</strong>：{candidate.summary}</p>
      <ul>{candidate.judgments.map(judgment => <li key={judgment.criterion_id}>
        <strong>{batch.result.criteria.find(c => c.criterion_id === judgment.criterion_id)?.description}</strong>
        ：{statuses[judgment.status]} · {judgmentBasis(judgment)}<p>{judgment.reason}</p>
        {judgment.evidence_refs.length > 0 && <details><summary>查看当时引用的证据（{judgment.evidence_refs.length}）</summary>
          {judgment.evidence_refs.map(ref => <EvidenceExcerpt key={ref} value={batch.evidence_refs[ref]} />)}
        </details>}
      </li>)}</ul>
    </article>)}
  </details>;
}

export function EvidenceExcerpt({ value }: { value: unknown }) {
  if (!value || typeof value !== "object" || !("data" in value)) return <p>证据摘录不可用</p>;
  const data = value.data as { evidence_json?: string };
  if (!data?.evidence_json) return <p>请查看商品证据</p>;
  try {
    const excerpt = JSON.parse(data.evidence_json) as { title?: string; price_text?: string; location?: string;
      search_description?: string; raw_text_excerpt?: string; statement_text?: string; kind?: string; detail?: { description?: string } };
    return <blockquote><p>{[excerpt.title, excerpt.price_text, excerpt.location].filter(Boolean).join(" · ")}</p>
      {excerpt.statement_text && <p className="muted">{excerpt.kind === "seller_reply" ? "用户转述卖家答复" : "用户本人观察"}，未经独立核实</p>}
      <p className="message-content">{excerpt.statement_text ?? excerpt.detail?.description ?? excerpt.raw_text_excerpt ?? excerpt.search_description ?? "没有描述"}</p>
      <details><summary>完整保存内容</summary><p className="message-content">{data.evidence_json}</p></details>
    </blockquote>;
  } catch {
    return <p>证据摘录不可用</p>;
  }
}
