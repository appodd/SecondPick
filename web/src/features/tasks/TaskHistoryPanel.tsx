import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { TaskDetail } from "../../api/types";

function unique<T>(items: T[], key: (value: T) => number): T[] {
  return [...new Map(items.map(value => [key(value), value])).values()].sort((a, b) => key(a) - key(b));
}

export function TaskHistoryPanel({ task }: { task: TaskDetail }) {
  const initial = task.history_page;
  const query = useInfiniteQuery({
    queryKey: ["task", task.task.id, "metadata-history", initial?.next_cursor],
    initialPageParam: initial?.next_cursor ?? "",
    queryFn: ({ pageParam }) => api.getTaskHistory(task.task.id, pageParam),
    getNextPageParam: page => page.history_page?.next_cursor ?? undefined,
    enabled: false,
  });
  if (!initial) return null;
  const pages = [task, ...(query.data?.pages ?? [])];
  const revisions = unique(pages.flatMap(page => page.preference_revisions), item => item.id);
  const runs = unique(pages.flatMap(page => page.runs), item => item.run_id);
  const reports = unique(pages.flatMap(page => page.reports), item => item.id);
  const hasMore = query.data ? query.hasNextPage : initial.has_more;
  return <details className="shortlist-full-analysis">
    <summary>查看任务记录（需求修订、采集轮次与报告）</summary>
    <p role="status" aria-label="任务记录加载进度">已加载需求修订 {revisions.length}/{initial.total_counts.preference_revisions} · 采集轮次 {runs.length}/{initial.total_counts.runs} · 报告 {reports.length}/{initial.total_counts.reports}</p>
    <h3>需求修订</h3>
    {revisions.length ? <ul>{revisions.map(item => <li key={item.id}><p>{item.user_message}</p><p>{item.effective_goal}</p></li>)}</ul> : <p>暂无需求修订。</p>}
    <h3>采集轮次</h3>
    {runs.length ? <ul>{runs.map(item => <li key={item.run_id}>采集轮次 #{item.run_id}：{item.goal} · 保存 {item.listing_snapshot_count} 条商品快照</li>)}</ul> : <p>暂无采集轮次。</p>}
    <h3>报告</h3>
    {reports.length ? <ul>{reports.map(item => <li key={item.id}><a href={`/api/tasks/${task.task.id}/reports/${item.id}`}>{item.title}</a></li>)}</ul> : <p>暂无报告。</p>}
    {query.isError && <p role="alert">任务记录暂时无法读取，可重试加载。</p>}
    {(hasMore || query.isError) && <button disabled={query.isFetching} onClick={() => void query.fetchNextPage()}>
      {query.isFetching ? "正在加载任务记录…" : "加载更早任务记录"}
    </button>}
  </details>;
}
