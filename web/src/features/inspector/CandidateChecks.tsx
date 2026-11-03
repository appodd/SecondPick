import { useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { queries } from "../../api/queries";
import type { CandidateCheck, CheckChange, CheckStatementOption } from "../../api/types";
import { SuggestedChecks } from "./SuggestedChecks";
import { CheckReviewPanel } from "./CheckReviewPanel";

export function CandidateChecks({ taskId, listingId }: { taskId: number; listingId: number }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const client = useQueryClient();
  const query = useInfiniteQuery(queries.candidateChecks(taskId, listingId, open));
  const refresh = () => client.invalidateQueries({ queryKey: ["task", taskId, "listing", listingId, "checks"] });
  const create = useMutation({ mutationFn: () => api.createCheck(taskId, listingId, question, requestKey),
    onSuccess: async () => { setQuestion(""); setRequestKey(crypto.randomUUID()); await refresh(); } });
  const first = query.data?.pages[0];
  const items = [...new Map(query.data?.pages.flatMap(page => page.items).map(item => [item.id, item]) ?? []).values()];
  return <details className="inspector-block candidate-checks" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>待核实清单</summary>
    {open && <>
      <p className="muted">手动记录本商品的问题和补充；关联答复不等于核实通过，也不会自动重评或访问平台。</p>
      <SuggestedChecks taskId={taskId} listingId={listingId} />
      <form className="check-form" onSubmit={event => { event.preventDefault(); if (question.trim() && !create.isPending) create.mutate(); }}>
        <label>新增核实问题<textarea disabled={create.isPending} maxLength={1000} value={question} onChange={event => {
          setQuestion(event.target.value); setRequestKey(crypto.randomUUID()); create.reset();
        }} /></label>
        <button disabled={create.isPending || !question.trim()}>保存问题</button>
      </form>
      {create.error && <p role="alert">{create.error.message}</p>}
      {query.isPending && <p>正在读取核实清单…</p>}
      {query.error && <p role="alert">{query.error.message}<button onClick={() => void query.refetch()}>重试读取清单</button></p>}
      {first && <>
        <p className="muted">共 {first.total_count} 项 · 待核实 {first.counts.pending} · 已记录补充 {first.counts.evidence_linked} · 暂不跟进 {first.counts.dismissed}</p>
        {first.statements_truncated && <p className="muted">可关联最近 20 条当前补充，共 {first.statement_count} 条；较早原文仍在对话历史中。</p>}
        {items.length === 0 && <p>还没有保存核实问题。</p>}
        {items.map(item => <CheckItem key={item.id} item={item} sources={first.available_statements} refresh={refresh} />)}
        {query.hasNextPage && <button disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>加载更早核实事项</button>}
      </>}
    </>}
  </details>;
}

function CheckItem({ item, sources, refresh }: { item: CandidateCheck; sources: CheckStatementOption[]; refresh: () => Promise<unknown> }) {
  const [sourceId, setSourceId] = useState("");
  const [note, setNote] = useState("");
  const [notice, setNotice] = useState("");
  const selected = sources.find(source => String(source.id) === sourceId);
  const mutation = useMutation({
    mutationFn: (change: CheckChange) => api.changeCheck(item.task_id, item.listing_id, item.id, change),
    onSuccess: async () => { setNote(""); setNotice("已保存；补充仍需核实。"); await refresh(); },
    onError: () => { void refresh(); },
  });
  const save = (state: CheckChange["state"]) => {
    if (mutation.isPending || (state === "evidence_linked" && !selected)) return;
    mutation.mutate({ expected_revision_id: item.revision_id, state, ...(note.trim() ? { note } : {}),
      ...(state === "evidence_linked" && selected ? { statement_id: selected.id, statement_revision_id: selected.revision_id } : {}) });
  };
  return <section className="check-item" aria-label={`核实问题：${item.question}`}>
    <strong>{item.question}</strong>
    <p>{item.effective_state === "pending" ? "待核实" : item.effective_state === "dismissed" ? "暂不跟进" : "已记录补充，仍待核实"}</p>
    {item.needs_recheck && <p role="status">关联补充已撤回或归属/类型已更改，请重新核实。</p>}
    {item.statement_text && <details><summary>查看当时关联的原文</summary>
      <p className="muted">{item.statement_kind === "seller_reply" ? "用户转述卖家答复" : item.statement_kind === "user_observation" ? "用户本人观察" : "用户补充"} · 未经独立核实</p>
      <p className="message-content">{item.statement_text}</p></details>}
    {item.note && <p className="message-content">备注：{item.note}</p>}
    <CheckReviewPanel item={item} sources={sources} />
    <div className="check-form">
      <label>核实备注<textarea disabled={mutation.isPending} maxLength={2000} value={note} onChange={event => setNote(event.target.value)} /></label>
      {item.effective_state !== "dismissed" && <>
        <label>关联当前补充<select disabled={mutation.isPending} value={sourceId} onChange={event => setSourceId(event.target.value)}>
          <option value="">请选择已有补充原文</option>
          {sources.map(source => <option key={source.id} value={source.id}>{source.kind === "seller_reply" ? "卖家答复" : "本人观察"}：{source.statement_text.slice(0, 90)}</option>)}
        </select></label>
        {selected && <p className="message-content">{selected.statement_text}</p>}
        {!sources.length && <p className="muted">请先在对话中发送绑定本商品的卖家答复或本人观察，再关联。</p>}
        <button disabled={mutation.isPending || !selected} onClick={() => save("evidence_linked")}>关联补充</button>
        <button disabled={mutation.isPending} onClick={() => save("dismissed")}>暂不跟进此项</button>
      </>}
      {item.state !== "pending" && <button disabled={mutation.isPending} onClick={() => save("pending")}>重新核实</button>}
    </div>
    {notice && <p role="status">{notice}</p>}
    {mutation.error && <p role="alert">{mutation.error.message}</p>}
  </section>;
}
