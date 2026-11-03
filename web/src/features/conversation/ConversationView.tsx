import type { CandidatePage, TaskDetail } from "../../api/types";
import { CandidateCard } from "./CandidateCard";
import { ConversationTimeline } from "./ConversationTimeline";
import { useInfiniteQuery } from "@tanstack/react-query";
import { queries } from "../../api/queries";
import { TaskHistoryPanel } from "../tasks/TaskHistoryPanel";
import { useEffect, useRef, useState } from "react";

export interface ConversationViewProps {
  candidateError: Error | null;
  candidateIsLoading: boolean;
  taskDetail?: TaskDetail;
  candidatePage?: CandidatePage;
  selectedListingId?: number;
  onSelectListing: (listingId: number) => void;
}

export function ConversationView({
  candidateError,
  candidateIsLoading,
  taskDetail,
  candidatePage,
  selectedListingId,
  onSelectListing,
}: ConversationViewProps) {
  const history = useInfiniteQuery(queries.messages(taskDetail?.task.id ?? NaN));
  const hasMessages = history.data?.pages.some(page => page.items.length > 0);
  const [excerptOpen, setExcerptOpen] = useState(false);
  const excerptInitialized = useRef(false);
  useEffect(() => {
    excerptInitialized.current = false;
    setExcerptOpen(false);
  }, [taskDetail?.task.id]);
  useEffect(() => {
    if (history.data && !excerptInitialized.current) {
      excerptInitialized.current = true;
      setExcerptOpen(!hasMessages);
    }
  }, [history.data, hasMessages]);
  if (!taskDetail) {
    return <section className="conversation-view">加载对话...</section>;
  }

  const candidates = candidatePage?.candidates.slice(0, 4) ?? [];
  const revisions = [...taskDetail.preference_revisions].sort((left, right) =>
    left.created_at.localeCompare(right.created_at),
  );

  return (
    <section className="conversation-view" aria-label="对话时间线">
      <TaskHistoryPanel task={taskDetail} />
      {revisions.length > 0 && hasMessages && <details className="shortlist-full-analysis">
        <summary>查看当前购买要求（已更新）</summary>
        <p>{taskDetail.task.effective_goal}</p>
        <p className="muted">历史回答保留当时的判断，请结合更新后的要求查看后续分析。</p>
      </details>}
      {(!hasMessages || taskDetail.reports.length > 0) && <ol className="conversation-timeline">
        {!hasMessages && <>
        <li className="conversation-item conversation-item--user">
          <span className="conversation-item__label">原始目标</span>
          <p>{taskDetail.task.original_goal}</p>
        </li>
        {revisions.map((revision) => (
          <li
            className="conversation-item conversation-item--user"
            key={revision.id}
          >
            <span className="conversation-item__label">偏好更新</span>
            <p>{revision.user_message}</p>
          </li>
        ))}
        <li className="conversation-item conversation-item--state">
          <span className="conversation-item__label">当前任务状态</span>
          <p>{taskDetail.task.effective_goal}</p>
        </li>
        </>}
        {taskDetail.reports.length > 0 ? (
          <li className="conversation-item conversation-item--state">
            <span className="conversation-item__label">已保存报告</span>
            <ul className="report-links">
              {taskDetail.reports.map((report) => (
                <li key={report.id}>
                  <a href={`/api/tasks/${taskDetail.task.id}/reports/${report.id}`}>
                    {report.title}
                  </a>
                </li>
              ))}
            </ul>
          </li>
        ) : null}
      </ol>}

      {(candidates.length > 0 || candidateError || candidateIsLoading) && <details className="candidate-excerpt" open={excerptOpen}
        onToggle={event => { excerptInitialized.current = true; setExcerptOpen(event.currentTarget.open); }}>
        <summary id="candidate-excerpt-title" aria-label="当前候选摘录">当前候选摘录 <span>{candidatePage?.deduplicated_count ?? "–"} 条候选</span></summary>
        {candidateError ? (
          <p className="scoped-error" role="status">
            {candidateError.message}
          </p>
        ) : candidateIsLoading ? (
          <p className="muted">加载候选...</p>
        ) : (
          <div className="candidate-grid">
            {candidates.map((candidate) => (
              <CandidateCard
                candidate={candidate}
                key={candidate.listing_id}
                onSelectListing={onSelectListing}
                selected={candidate.listing_id === selectedListingId}
              />
            ))}
          </div>
        )}
      </details>}

      <ConversationTimeline key={taskDetail.task.id} taskId={taskDetail.task.id}
        taskDetail={taskDetail} candidates={candidatePage?.candidates}
        selectedListingId={selectedListingId}
        onSelectListing={onSelectListing} />
    </section>
  );
}
