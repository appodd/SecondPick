import type { Monitor } from "../../api/monitorClient";
import type { MonitorTask } from "./monitorTasks";
import { MonitorConsole } from "../monitor/MonitorConsole";
import { MonitorDiagnostics } from "../monitor/MonitorWorkspace";
import { ResponsiveDrawer } from "../../components/layout/ResponsiveDrawer";
import { date } from "./projectUi";
import "./monitor-logs.css";
import { ExecutionStatus, ProgressSummary, StatusBadge } from "../../components/status/ExecutionStatus";
import { monitorExecution, windowStatus } from "../../components/status/statusModel";

export function MonitorActivity({ monitor, name }: { monitor: Monitor; name: string }) {
  return <section className="sp-monitor-activity" aria-label={`${name} 采集进展`}>
    <ExecutionStatus status={monitorExecution(monitor)} />
    <ProgressSummary><span>已尝试 <b>{monitor.rounds}</b> 轮（含未成功的尝试）</span><span>累计商品记录 <b>{monitor.imported}</b>（已结束轮次，含补充版本）</span></ProgressSummary>
    {monitor.state === "waiting" && monitor.next_run_at ? <p className="sp-status-time">下轮计划：{date(monitor.next_run_at)}</p> : null}
    {monitor.result.sync_pending ? <p>已有记录等待同步，当前入库数可能不完整。</p> : null}
    <MonitorDiagnostics monitor={monitor} compact />
  </section>;
}

export function MonitorLogDetail({ task, initialRound, roundChanged, selectedRun, close }: {
  task: MonitorTask; initialRound: string; roundChanged: (value: string) => void; selectedRun?: number; close: () => void;
}) {
  const monitor = task.monitor;
  if (!monitor) return null;
  const run = task.window?.runs.find(item => item.id === selectedRun);
  return <div className="sp-monitor-log-overlay"><ResponsiveDrawer title={`${task.name} · 采集日志`} triggerLabel="查看监控采集日志" open onOpenChange={open => { if (!open) close(); }}>
    <div className="sp-log-detail"><h2>{task.name}</h2><p>{monitor.keyword} · 监控 #{task.id}</p>
      {run ? <div className="mt-log-context"><b>从 MonitorRun #{run.id} 进入</b>{" "}<StatusBadge status={windowStatus(run, monitor)} live={["running", "paused"].includes(run.state)} /><p>窗口开启 {date(run.started_at)} · 结束 {date(run.finished_at)}</p></div> : null}
      <p className="sp-log-note">按采集器真实轮次选择日志。执行窗口与日志轮次尚无精确关联，默认“最新一轮”不能解释为所选 MonitorRun 的对应日志。</p>
      <MonitorConsole key={task.id} monitor={monitor} initialRound={initialRound} onRoundChange={roundChanged} />
      <details><summary>关键采集事件</summary><MonitorDiagnostics monitor={monitor} /></details>
    </div>
  </ResponsiveDrawer></div>;
}
