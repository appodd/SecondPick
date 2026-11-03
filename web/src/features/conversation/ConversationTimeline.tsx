import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Fragment, useEffect, useState } from "react";
import { api } from "../../api/client";
import { browserStatusQuery } from "../../api/browserClient";
import { queries } from "../../api/queries";
import type { CandidateSummary, TaskDetail, CandidateStatementInput } from "../../api/types";
import { StructuredAssessment } from "./StructuredAssessment";
import { StatementBindingControls } from "./StatementBindingControls";
import { VersionedComparison, ReviewProgress } from "./VersionedComparison";
import { useOperationEvents } from "../../hooks/useOperationEvents";
import { ConversationComposer } from "./ConversationComposer";
import { ActionRequestCard } from "./ActionRequestCard";
import { OperationStatus } from "./OperationStatus";
import { CandidateCard } from "./CandidateCard";
import { ShortlistComparison } from "./ShortlistComparison";
import { applyCurrentInputs } from "./researchValidity";

function uniqueRecords<T extends { id: number }>(records: T[]): T[] {
  return [...new Map(records.map(item => [item.id, item])).values()].sort((a, b) => a.id - b.id);
}

export function ConversationTimeline({ taskId, taskDetail, candidates = [], selectedListingId, onSelectListing = () => {} }: {
  selectedListingId?: number;
  taskId?: number; taskDetail?: TaskDetail; candidates?: CandidateSummary[]; onSelectListing?: (id: number) => void;
}) {
  const client = useQueryClient();
  const browser = useQuery(browserStatusQuery());
  const navigate = useNavigate();
  const history = useInfiniteQuery(queries.messages(taskId ?? NaN));
  const research = useInfiniteQuery({ ...queries.researchHistory(taskId ?? NaN),
    enabled: taskId !== undefined && taskDetail?.research !== undefined,
  });
  const requests = useInfiniteQuery(queries.actionRequests(taskId ?? NaN));
  const messages = history.data?.pages.flatMap(page => page.items).sort((a, b) => a.id - b.id) ?? [];
  const actions = requests.data?.pages.flatMap(page => page.items).sort((a, b) => a.id - b.id) ?? [];
  const latestShortlistId = messages.filter(message => message.role === "assistant" && message.candidate_ids.length > 0).at(-1)?.id;
  const researchSources = [...(research.data?.pages ?? []).slice().reverse(), ...(taskDetail?.research ? [taskDetail.research] : [])];
  const currentRevision = taskDetail?.preference_revision_id ?? Math.max(0, ...(taskDetail?.preference_revisions.map(revision => revision.id) ?? []));
  const currentSignature = taskDetail?.research?.page?.evidence_signature;
  const assessmentBatches = applyCurrentInputs(uniqueRecords(researchSources.flatMap(page => page.assessment_batches)), currentRevision, currentSignature);
  const comparisonRecords = applyCurrentInputs(uniqueRecords(researchSources.flatMap(page => page.comparisons ?? [])), currentRevision, currentSignature);
  const reviewRecords = applyCurrentInputs(uniqueRecords(researchSources.flatMap(page => page.reviews ?? [])), currentRevision, currentSignature);
  const comparisons = new Map(comparisonRecords.map(value => [value.operation_id, value]));
  const reviews = new Map(reviewRecords.map(value => [value.operation_id, value]));
  const totals = taskDetail?.research?.page?.total_counts ?? research.data?.pages[0]?.page?.total_counts;
  const messageOperations = new Set(messages.map(message => message.operation_id));
  const olderBatches = assessmentBatches.filter(batch => !messageOperations.has(batch.operation_id));
  const olderComparisons = comparisonRecords.filter(snapshot => !messageOperations.has(snapshot.operation_id));
  const olderReviews = reviewRecords.filter(review => !messageOperations.has(review.operation_id));
  const [submittedOperationId, setSubmittedOperationId] = useState<number>();
  const operationId = Math.max(messages.at(-1)?.operation_id ?? 0, submittedOperationId ?? 0) || undefined;
  const operation = useQuery(queries.operation(operationId));
  const events = useOperationEvents(operation.data);
  const state = operation.data?.operation.state;
  useEffect(() => {
    if (state && state !== "queued" && state !== "running") {
      // Fast completion can precede the SSE connection, including saved research.
      void client.invalidateQueries({ queryKey: ["task", taskId] });
    }
  }, [state, operationId, taskId, client]);
  const collecting = taskId !== undefined && browser.data?.active_job?.task_id === taskId;
  const blocked = collecting || state === "queued" || state === "running" || state === "waiting_confirmation";
  const send = useMutation({ mutationFn: async ({ message, statement }: { message: string; statement?: CandidateStatementInput }) => {
    const result = taskId ? await api.sendMessage(taskId, message, statement) : await api.createTask(message);
    const savedTaskId = result.operation.task_id;
    client.setQueryData(["operation", result.operation.id], { operation: result.operation, last_event_id: 0, action_request: null });
    // Follow the accepted operation immediately while the message list refetches.
    setSubmittedOperationId(result.operation.id);
    // Invalidate before navigation so a previously mounted task cannot show stale history.
    await client.invalidateQueries({ queryKey: statement ? ["task", savedTaskId] : ["task", savedTaskId, "messages"] });
    void client.invalidateQueries({ queryKey: ["tasks"] });
    if (!taskId) navigate(`/tasks/${savedTaskId}`, { replace: true });
  }, onError: () => {
    if (taskId) void client.invalidateQueries({ queryKey: ["task", taskId, "messages"] });
  } });
  const cancel = useMutation({ mutationFn: () => api.cancelOperation(operationId!), onSuccess: result => {
    client.setQueryData(["operation", operationId], result);
    void client.invalidateQueries({ queryKey: ["task", taskId, "messages"] });
  } });
  const unavailable = taskId !== undefined && (history.isPending || history.isError || requests.isError || requests.isPending || (operationId !== undefined && !operation.data));
  function requestsAfter(message: (typeof messages)[number]) {
    const turn = messages.filter(item => item.operation_id === message.operation_id);
    const anchor = turn.filter(item => item.role === "assistant").at(-1) ?? turn.at(-1);
    return anchor?.id === message.id ? actions.filter(action => action.operation_id === message.operation_id) : [];
  }
  function historicalCandidates(message: (typeof messages)[number]) {
    return <div className="candidate-grid">{message.candidate_ids.map(id => {
      const candidate = candidates.find(item => item.listing_id === id);
      return candidate ? <CandidateCard key={id} candidate={candidate} selected={false} onSelectListing={onSelectListing} /> : <button key={id} onClick={() => onSelectListing(id)}>查看商品 #{id} 的证据</button>;
    })}</div>;
  }
  return <section className="conversation-flow" aria-label="持久化对话">
    {!taskId && <div className="new-conversation-intro"><p className="workspace-eyebrow">新研究</p><h1 id="workspace-title">这次，想找什么？</h1><p>说说预算、用途和偏好。我们会结合已保存的商品证据，一起梳理选择。</p></div>}
    {history.isLoading && taskId && <p>加载对话…</p>}
    {(history.error || requests.error || operation.error) && <p className="scoped-error" role="alert">{history.error?.message ?? requests.error?.message ?? operation.error?.message} <button onClick={() => { void history.refetch(); void requests.refetch(); void operation.refetch(); }}>重试</button></p>}
    {history.hasNextPage && <button onClick={() => void history.fetchNextPage()} disabled={history.isFetchingNextPage}>加载更早消息</button>}
    <ol className="conversation-timeline">
      {messages.map(message => <Fragment key={message.id}><li className={`conversation-item conversation-item--${message.role}`}>
        {message.candidate_statement && taskId !== undefined && <StatementBindingControls taskId={taskId} binding={message.candidate_statement} onSelectListing={onSelectListing} locked={collecting || operation.data?.operation.state === "waiting_confirmation"} />}
        {message.role === "system" ? <details className="conversation-system-record"><summary>{message.content.split("。")[0]}</summary><p className="message-content">{message.content}</p></details> :
          <><span className="conversation-item__label">{message.role === "user" ? "你" : "研究助手"}</span>{message.role === "assistant" && comparisons.has(message.operation_id!) ? <>
            <p className="message-content">{message.content}</p>
            <VersionedComparison snapshot={comparisons.get(message.operation_id!)!} batches={assessmentBatches} onSelectListing={onSelectListing} />
          </> : message.id === latestShortlistId ? <>
            <p className="message-content">{message.content.split(/\n\s*\n/)[0].split(/(?<=[。！？])\s*/u)[0]}</p>
            <ShortlistComparison message={message} candidates={candidates} onSelectListing={onSelectListing} />
            <details className="shortlist-full-analysis"><summary>查看完整分析与建议</summary><p className="message-content">{message.content}</p></details>
          </> : message.role === "assistant" && message.candidate_ids.length > 0 ? <details className="shortlist-history"><summary>查看此前的分析与 {message.candidate_ids.length} 条候选</summary><p className="message-content">{message.content}</p>{historicalCandidates(message)}</details> : <p className="message-content">{message.content}</p>}</>}
        {message.role !== "assistant" && message.candidate_ids.length > 0 && historicalCandidates(message)}
        {message.role !== "assistant" && reviews.has(message.operation_id!) && <ReviewProgress review={reviews.get(message.operation_id!)!}
          batches={assessmentBatches.filter(batch => batch.operation_id === message.operation_id)} onSelectListing={onSelectListing} />}
        {message.role === "assistant" && assessmentBatches.filter(batch => batch.operation_id === message.operation_id).map(batch =>
          <StructuredAssessment key={batch.id} batch={batch} onSelectListing={onSelectListing} />)}
      </li>{requestsAfter(message).map(action => <li className="conversation-action" key={action.id}><ActionRequestCard request={action} /></li>)}</Fragment>)}
    </ol>
    {(olderBatches.length > 0 || olderComparisons.length > 0 || olderReviews.length > 0) && <details>
      <summary>已加载的更早研究记录</summary>
      <p className="muted">这些记录对应的较早对话尚未加载，可在上方加载更早消息。</p>
      {olderReviews.map(review => <ReviewProgress key={review.id} review={review}
        batches={olderBatches.filter(batch => batch.operation_id === review.operation_id)} onSelectListing={onSelectListing} />)}
      {olderComparisons.map(snapshot => <VersionedComparison key={snapshot.id} snapshot={snapshot} batches={assessmentBatches} onSelectListing={onSelectListing} />)}
      {olderBatches.map(batch => <StructuredAssessment key={batch.id} batch={batch} onSelectListing={onSelectListing} />)}
    </details>}
    {totals && (totals.assessment_batches + totals.reviews + totals.comparisons > 0) && <section aria-label="研究记录加载进度">
      <p className="muted">已加载评估 {assessmentBatches.length}/{totals.assessment_batches} 批 · 重评 {reviewRecords.length}/{totals.reviews} 次 · 比较 {comparisonRecords.length}/{totals.comparisons} 次</p>
      {research.hasNextPage && <button disabled={research.isFetchingNextPage} onClick={() => void research.fetchNextPage()}>加载更早研究记录</button>}
    </section>}
    {research.error && <p role="alert">历史研究记录暂时无法读取。<button onClick={() => void research.refetch()}>重试</button></p>}
    {actions.filter(action => !messages.some(message => message.operation_id === action.operation_id)).map(action => <ActionRequestCard key={action.id} request={action} />)}
    {requests.hasNextPage && <button disabled={requests.isFetchingNextPage} onClick={() => void requests.fetchNextPage()}>加载更早请求</button>}
    {!messages.length && taskDetail && !history.isPending && <p className="muted">继续聊聊这个研究任务，消息将自动保存。</p>}
    {operation.data && !collecting && <OperationStatus operation={operation.data.operation} stage={events.stage} reconnecting={events.reconnecting} onStop={() => cancel.mutate()} stopping={cancel.isPending} />}
    {collecting && <p role="status" className="muted">正在采集当前任务的证据。采集完成或停止后可继续发送消息。</p>}
    {cancel.error && <p role="alert" className="scoped-error">{cancel.error.message}</p>}
    <ConversationComposer disabled={blocked || unavailable} pending={send.isPending} allowStatements={taskId !== undefined} selectedListingId={selectedListingId}
      onSend={(message, statement) => send.mutateAsync({ message, statement })} />
  </section>;
}
