import { useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { queries } from "../../api/queries";
import type { CandidateCheck, CheckReview, CheckReviewChange, CheckReviewOutcome, CheckStatementOption } from "../../api/types";

const outcomes = { answered: "已有答复", uncertain: "仍不确定", conflict: "存在冲突" };
export function CheckReviewPanel({ item, sources }: { item: CandidateCheck; sources: CheckStatementOption[] }) {
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<CheckReviewOutcome>("uncertain");
  const [summary, setSummary] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [notice, setNotice] = useState("");
  const client = useQueryClient();
  const query = useInfiniteQuery(queries.checkReviews(item.task_id, item.listing_id, item.id, open));
  const first = query.data?.pages[0];
  const entries = [...new Map(query.data?.pages.flatMap(p => p.items).map(r => [r.id, r]) ?? []).values()];
  const refresh = () => client.invalidateQueries({ queryKey: ["task", item.task_id, "listing", item.listing_id] });
  const save = useMutation({ mutationFn: (change: CheckReviewChange) => api.changeCheckReview(item.task_id, item.listing_id, item.id, change),
    onSuccess: async () => { setSummary(""); setSelected([]); setNotice("已保存用户记录；不代表独立核验或条件符合。"); await refresh(); },
    onError: () => { void refresh(); } });
  const currentSources = sources.filter(s => selected.includes(s.id));
  const submit = (action: "record" | "withdraw") => {
    if (!first || save.isPending) return;
    save.mutate({ action, expected_review_id: first.latest_review_id, expected_check_revision_id: first.check_revision_id,
      expected_basis_token: first.basis_token, ...(action === "record" ? { outcome, summary, sources: currentSources.map(s => ({ statement_id: s.id, revision_id: s.revision_id })) } : {}) });
  };
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>核实记录与来源</summary>
    {open && <section aria-label={`核实记录：${item.question}`}>
      <p className="muted">记录你对原文的理解，不能证明商品符合要求。最多选择 5 条当前补充；冲突需至少两条不同原文。记录可更正或撤回，旧版本保留。</p>
      {query.isPending && <p>正在读取核实记录…</p>}
      {query.error && <p role="alert">{query.error.message}<button onClick={() => void query.refetch()}>重试读取核实记录</button></p>}
      {first && <>
        {first.current_review ? <ReviewRecord review={first.current_review} /> : <p>尚无用户核实记录。</p>}
        <div className="check-form">
          <label>用户记录状态<select disabled={save.isPending} value={outcome} onChange={e => setOutcome(e.target.value as CheckReviewOutcome)}>
            {Object.entries(outcomes).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
          </select></label>
          <label>记录说明<textarea maxLength={2000} disabled={save.isPending} value={summary} onChange={e => setSummary(e.target.value)} /></label>
          <fieldset disabled={save.isPending}><legend>依据的当前补充</legend>
            {sources.map(s => <label className="review-source-choice" key={s.id}>
              <input type="checkbox" checked={selected.includes(s.id)} disabled={!selected.includes(s.id) && selected.length >= 5} onChange={e => setSelected(ids => e.target.checked ? [...ids, s.id] : ids.filter(id => id !== s.id))} />
              <span>{s.kind === "seller_reply" ? "卖家答复" : "本人观察"}：{s.statement_text}</span>
            </label>)}
            {!sources.length && <p>请先在对话中发送绑定本商品的补充原文。</p>}
          </fieldset>
          <button disabled={save.isPending || item.effective_state === "dismissed" || !summary.trim() || currentSources.length < (outcome === "conflict" ? 2 : 1)} onClick={() => submit("record")}>保存用户核实记录</button>
          {first.current_review && first.current_review.action !== "withdraw" && <button disabled={save.isPending} onClick={() => submit("withdraw")}>撤回本条核实记录</button>}
        </div>
        <details><summary>核实记录历史（{first.total_count}）</summary>
          {entries.map(r => <ReviewRecord key={r.id} review={r} />)}
          {query.hasNextPage && <button disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>加载更早核实记录</button>}
        </details>
      </>}
      {notice && <p role="status">{notice}</p>}
      {save.error && <p role="alert">{save.error.message}</p>}
    </section>}
  </details>;
}

function ReviewRecord({ review }: { review: CheckReview }) {
  return <div className="check-item">
    <p><strong>{review.action === "withdraw" ? "用户已撤回记录" : `用户记录：${outcomes[review.outcome!]}`}</strong> · 未经独立核实</p>
    {review.status === "needs_recheck" && <p role="status">来源、问题、要求或商品证据已变化，请重新核实。</p>}
    {review.status === "superseded" && <p className="muted">历史版本，已被后续记录替代。</p>}
    {review.summary && <p className="message-content">{review.summary}</p>}
    {review.sources.map(s => <details key={s.statement_id}><summary>{s.kind === "seller_reply" ? "当时卖家答复" : "当时本人观察"}{!s.current && "（来源已变化）"}</summary><p className="message-content">{s.statement_text ?? "原文不可用"}</p></details>)}
  </div>;
}
