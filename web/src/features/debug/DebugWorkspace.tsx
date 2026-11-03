import { Activity, FileText, Search } from "lucide-react";

import type { DebugSnapshot } from "../../api/types";
import { AccessEventTable } from "./AccessEventTable";

export function DebugWorkspace({ snapshot }: { snapshot: DebugSnapshot }) {
  const coverage = snapshot.search_coverage;

  return (
    <section className="debug-workspace" aria-labelledby="debug-title">
      <header className="debug-workspace__header">
        <p className="workspace-eyebrow">任务 #{snapshot.task.id}</p>
        <h1 id="debug-title">调试视图</h1>
      </header>

      <section className="debug-section" aria-labelledby="coverage-title">
        <div className="debug-section__heading"><Search aria-hidden="true" size={18} /><h2 id="coverage-title">搜索覆盖</h2></div>
        <dl className="debug-summary-grid">
          <div><dt>唯一候选</dt><dd>{coverage.unique_candidates} / {coverage.target_min}–{coverage.target_max}</dd></div>
          <div><dt>覆盖状态</dt><dd>{coverage.status}</dd></div>
          <div><dt>低收益连续次数</dt><dd>{coverage.low_gain_streak}</dd></div>
          <div><dt>建议动作</dt><dd>{coverage.suggested_action}</dd></div>
        </dl>
      </section>

      <section className="debug-section" aria-labelledby="runs-title">
        <div className="debug-section__heading"><Activity aria-hidden="true" size={18} /><h2 id="runs-title">关联运行</h2></div>
        {snapshot.runs.length === 0 ? <p className="muted">暂无运行记录。</p> : (
          <div className="debug-run-list">
            {snapshot.runs.map((run) => {
              const runCoverage = coverage.runs.find((item) => item.run_id === run.run_id);
              return (
                <article className="debug-run" key={run.run_id}>
                  <div><strong>Run #{run.run_id}</strong></div>
                  <ul>
                    <li>查询 {run.query_count}</li>
                    <li>页面快照 {run.page_snapshot_count}</li>
                    <li>详情快照 {run.listing_snapshot_count}</li>
                    <li>新增候选 {runCoverage?.new_unique_count ?? "—"}</li>
                  </ul>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="debug-section" aria-labelledby="reports-title">
        <div className="debug-section__heading"><FileText aria-hidden="true" size={18} /><h2 id="reports-title">报告记录</h2></div>
        {snapshot.reports.length === 0 ? <p className="muted">暂无报告。</p> : (
          <ul className="debug-report-list">
            {snapshot.reports.map((report) => <li key={report.id}><strong>报告 #{report.id}</strong></li>)}
          </ul>
        )}
      </section>

      <AccessEventTable data={snapshot.global_platform_access_events} />
    </section>
  );
}
