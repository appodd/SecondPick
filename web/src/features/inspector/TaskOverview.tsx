import type { CandidatePage, MarketOverview, TaskDetail } from "../../api/types";

function currentPreferences(taskDetail: TaskDetail) {
  if (taskDetail.current_preferences) return taskDetail.current_preferences;
  const preferences = new Set<string>();

  for (const revision of taskDetail.preference_revisions) {
    for (const preference of revision.removed_preferences) {
      preferences.delete(preference);
    }
    for (const preference of revision.added_preferences) {
      preferences.add(preference);
    }
  }

  return [...preferences];
}

export function TaskOverview({
  candidatePage,
  market,
  taskDetail,
}: {
  candidatePage?: CandidatePage;
  market?: MarketOverview;
  taskDetail?: TaskDetail;
}) {
  if (!taskDetail) {
    return <p className="muted">加载任务概览...</p>;
  }

  const preferences = currentPreferences(taskDetail);

  return (
    <section className="task-overview" aria-labelledby="task-overview-title">
      <div className="inspector-section-heading">
        <p>{taskDetail.task.title}</p>
        <h2 id="task-overview-title">任务概览</h2>
      </div>
      <section className="inspector-block">
        <h3>目标</h3>
        <dl className="inspector-facts inspector-facts--stacked">
          <div><dt>原始目标</dt><dd>{taskDetail.task.original_goal}</dd></div>
          <div><dt>当前目标</dt><dd>{taskDetail.task.effective_goal}</dd></div>
        </dl>
      </section>
      <section className="inspector-block">
        <h3>偏好</h3>
        {preferences.length > 0 ? (
          <ul className="compact-list">{preferences.map((item) => <li key={item}>{item}</li>)}</ul>
        ) : <p className="muted">没有单独记录的新增偏好。</p>}
        {taskDetail.current_preferences_truncated && <p className="muted">仅列出最近保留的 50 条偏好，完整要求请以当前目标为准。</p>}
      </section>
      <dl className="inspector-facts">
        <div><dt>覆盖状态</dt><dd>{taskDetail.search_coverage.status}</dd></div>
        <div><dt>唯一候选</dt><dd>{candidatePage?.deduplicated_count ?? taskDetail.search_coverage.unique_candidates}</dd></div>
        <div><dt>价格中位数</dt><dd>{market?.overall?.price_summary?.median ?? "未计算"}</dd></div>
        <div><dt>关联运行</dt><dd>{taskDetail.history_page?.total_counts.runs ?? taskDetail.runs.length}</dd></div>
      </dl>
      <section className="inspector-block">
        <h3>设置限制</h3>
        <p className="muted">对话基于本地已保存的证据。确认请求后，可核对范围并点击“执行采集”补充搜索和详情证据。</p>
      </section>
    </section>
  );
}
