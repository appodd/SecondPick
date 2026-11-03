import type { AssessmentBatch, ComparisonSnapshot, HistoryReview, ReviewCoverage } from "../../api/types";
import { StructuredAssessment } from "./StructuredAssessment";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { queries } from "../../api/queries";

export function Coverage({ value }: { value: ReviewCoverage }) {
  return <p className="muted">已保存范围 {value.scope_count} 件 · 已审视 {value.reviewed_count} 件 · 已逐项评估 {value.assessed_count} 件 · 待处理 {value.pending_count} 件{value.truncated ? "（范围截断）" : ""}</p>;
}

export function ReviewProgress({ review, batches, onSelectListing }: {
  review: HistoryReview; batches: AssessmentBatch[]; onSelectListing: (id: number) => void;
}) {
  const terminal = ["failed", "cancelled", "interrupted"].includes(review.state);
  return <section aria-label="历史候选重评进度" className="shortlist-comparison">
    <strong>{review.stale ? "历史重评（要求或证据已变化）" : terminal ? "候选重评未完成" : review.state === "completed" ? "候选重评已完成" : "正在重评已保存候选"}</strong>
    <Coverage value={review.coverage} />
    {review.nomination_progress?.required && <p className="muted">重新提名进度：已保存 {review.nomination_progress.completed_groups}/{review.nomination_progress.total_groups} 组；{review.nomination_progress.pending_groups ? "完成后生成完整比较。" : "提名已完成。"}</p>}
    {terminal && <p>已完成的评估仍保留，本次未发布新比较。可继续发送“重评历史候选”，复用有效评估并完成剩余评估或提名。</p>}
    {terminal && batches.map(batch => <StructuredAssessment key={batch.id} batch={batch} onSelectListing={onSelectListing} />)}
  </section>;
}

export function VersionedComparison({ snapshot, batches, onSelectListing }: {
  snapshot: ComparisonSnapshot; batches: AssessmentBatch[]; onSelectListing: (id: number) => void;
}) {
  return <section aria-label="已保存的候选比较" className="shortlist-comparison">
    <h2>{snapshot.stale ? "历史候选比较（要求或证据已变化）" : "本轮候选比较"}</h2>
    <Coverage value={snapshot.coverage} />
    <p className="muted">排序、理由与未知来自当时保存的逐项评估。卖家声明仍需核实。</p>
    {snapshot.stale && <p>此比较依据旧输入，请查看后续重评；历史内容保留不变。</p>}
    {snapshot.result.ranked_candidates.length === 0 && <p>本轮没有列入推荐的候选。</p>}
    <ol>{snapshot.result.ranked_candidates.map(entry => {
      const batch = batches.find(b => b.id === entry.assessment_id);
      return <li key={entry.listing_id}>
        <button onClick={() => onSelectListing(entry.listing_id)}>查看商品 #{entry.listing_id} 的证据</button>
        <p>{entry.reason}</p>
        {entry.uncertainties.length > 0 && <ul>{entry.uncertainties.map((text, i) => <li key={i}>待核实：{text}</li>)}</ul>}
        <AssessmentReference taskId={snapshot.task_id} listingId={entry.listing_id} assessmentId={entry.assessment_id} cached={batch} />
      </li>;
    })}</ol>
    {snapshot.result.changes.length > 0 && <details open><summary>候选变化及原因</summary>
      <ul>{snapshot.result.changes.map(change => <li key={change.listing_id}>
        商品 #{change.listing_id} {change.kind === "entered" ? "进入本轮比较" : "退出本轮比较"}：{change.reason}
      </li>)}</ul>
    </details>}
  </section>;
}

function AssessmentReference({ taskId, assessmentId, listingId, cached }: {
  taskId: number; assessmentId: number; listingId: number; cached?: AssessmentBatch;
}) {
  const [open, setOpen] = useState(false);
  const query = useQuery(queries.assessment(taskId, assessmentId, open && !cached));
  const batch = cached ?? query.data;
  const item = batch?.result.assessments.find(a => a.listing_id === listingId);
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>查看本次排序引用的评估</summary>
    {open && <>
      {!batch && query.isPending && <p>正在读取当时保存的评估…</p>}
      {query.error && !batch && <p role="alert">评估暂时无法读取。<button onClick={() => void query.refetch()}>重试</button></p>}
      {item && <><p>{item.summary}</p><ul>{item.judgments.map(j => <li key={j.criterion_id}>
        {batch?.result.criteria.find(c => c.criterion_id === j.criterion_id)?.description}：{j.reason}
      </li>)}</ul></>}
    </>}
  </details>;
}
