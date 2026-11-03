import { Link } from "react-router-dom";
import type { MonitorTask } from "./monitorTasks";
import { monitorCycle, monitorMode } from "./monitorTasks";
import { MonitorActivity } from "./MonitorLogDetail";
import { MonitorDiagnostics } from "../monitor/MonitorWorkspace";
import { MonitorTaskActions } from "./MonitorTaskActions";
import { ResponsiveDrawer } from "../../components/layout/ResponsiveDrawer";
import { ExecutionStatus, SnapshotNotice, StatusBadge } from "../../components/status/ExecutionStatus";
import { monitorExecution, monitorScheduling, windowStatus } from "../../components/status/statusModel";
import { date } from "./projectUi";
import { useEntryHref } from "./contextNavigation";

export function MonitorTaskDetail({ task, projectId, selectedRun, selectRun, logs, edit, close }: {
  task: MonitorTask; projectId: number; selectedRun?: number; selectRun: (id: number) => void;
  logs: (run?: number) => void; edit: () => void; close: () => void;
}) {
  const monitor = task.monitor;
  const entry = useEntryHref(projectId);
  const run = task.window?.runs.find(item => item.id === selectedRun);
  return <div className="mt-detail-overlay"><ResponsiveDrawer title={`${task.name} · 监控详情`} triggerLabel="查看监控任务详情" open onOpenChange={open => { if (!open) close(); }}>
    <div className="mt-detail">
      <div className="sp-between"><h2>{task.name}</h2><StatusBadge status={monitorScheduling(monitor)} live /></div>
      <p className="sp-muted">监控 #{task.id} · {monitorMode(task)} · {monitorCycle(task)}</p>
      <SnapshotNotice />
      <section aria-label="搜索与运行规则"><div className="sp-between"><h3>搜索与运行规则</h3>{task.window && monitor ? <button onClick={edit}>检查并编辑规则</button> : null}</div>
        {monitor ? <dl className="mt-rules">
          <div><dt>搜索关键词</dt><dd>{monitor.keyword}</dd></div>
          <div><dt>运行模式</dt><dd>{monitorMode(task)}</dd></div><div><dt>执行周期</dt><dd>{monitorCycle(task)}</dd></div>
          {task.window?.mode === "timed" ? <div><dt>每次执行窗口时长</dt><dd>{task.window.duration_seconds === null ? "未提供" : `${task.window.duration_seconds / 60} 分钟`}</dd></div> : null}
          <div><dt>每轮搜索上限</dt><dd>{monitor.max_pages} 页</dd></div><div><dt>每轮新增详情上限</dt><dd>{monitor.max_items} 件</dd></div>
          <div><dt>卖家公开主页与发布记录</dt><dd>{monitor.collect_seller_profiles ? "已允许采集" : "未允许采集"}</dd></div>
          <div><dt>已确认轮次上限</dt><dd>{monitor.max_rounds} 轮（包含失败尝试）</dd></div>
        </dl> : <p>当前执行数据未提供，配置和操作暂不可确认。</p>}
        {task.source === "native" ? <p className="sp-muted">当前未返回工作区窗口或可编辑修订信息。需要新规则时请创建新范围并确认，原记录保留。<Link to={entry(`/tasks/${projectId}?tab=monitor`)}>查看原有范围管理 ↗</Link></p> : null}
        <p className="sp-muted">配置上限不是已处理总量。保存永久变更前须暂停并等待采集退出，仍需预览和明确确认；保存不会自动运行。</p>
      </section>
      <section aria-label="当前采集与最近活动"><h3>当前采集与最近活动</h3>
        {monitor ? <MonitorActivity monitor={monitor} name={task.name} /> : <ExecutionStatus status={monitorExecution(monitor)} />}
        <MonitorTaskActions task={task} projectId={projectId} />
        <p className="sp-muted">暂停/停止监控均包含当前采集及后续调度；已收集商品的 Agent 研究独立继续。</p>
      </section>
      <section aria-label="执行历史"><div className="sp-between"><h3>执行历史</h3><small>{task.window ? `${task.window.runs.length} 次执行窗口` : "窗口记录未返回"}</small></div>
        {task.window?.runs.length ? <div className="mt-run-list">{task.window.runs.map(item => <button key={item.id} className="mt-run-select" aria-pressed={selectedRun === item.id} onClick={() => selectRun(item.id)}>
          <span><strong>MonitorRun #{item.id}</strong><small>窗口开启 {date(item.started_at)}</small></span><StatusBadge status={windowStatus(item, monitor)} live={["running", "paused"].includes(item.state)} /><span aria-hidden="true">›</span>
        </button>)}</div> : <p className="sp-muted">{task.source === "native" ? "原监控未提供 MonitorRun 执行窗口；可查看实际采集轮次日志与事件。" : "尚无执行窗口记录。"}</p>}
        {run ? <div className="mt-selected-run" aria-label={`MonitorRun #${run.id} 详情`}>
          <div className="sp-between"><h4>MonitorRun #{run.id}</h4><StatusBadge status={windowStatus(run, monitor)} live={["running", "paused"].includes(run.state)} /></div>
          <p>窗口开启 {date(run.started_at)} · 结束 {date(run.finished_at)}{run.deadline_at ? ` · 截止 ${date(run.deadline_at)}` : ""}</p>
          {run.counts ? <p>该窗口入库记录 {run.counts.records} 条 · 涉及去重商品 {run.counts.unique_listings} 件，不等于项目去重新增。</p> : null}
          {run.config ? <p>执行时规则：{run.config.keyword} · 每轮最多 {run.config.max_pages} 页 · 新增详情最多 {run.config.max_items} 件。</p> : null}
          {run.error ? <p className="sp-error">后端错误：{run.error}</p> : null}
          <p className="sp-muted">窗口有效不等于采集正在执行；窗口已结束不一定是成功完成。</p>
          <button data-open-logs onClick={() => logs(run.id)}>查看该任务采集日志</button>
          <p className="sp-muted">当前没有窗口与采集器轮次的精确关联，日志需要按真实采集轮次选择。</p>
        </div> : null}
      </section>
      <section aria-label="采集日志与诊断"><h3>采集日志与诊断</h3><p className="sp-muted">完整输出独立查看，保留自动刷新、跟随最新与历史轮次切换。</p>
        <button data-open-logs onClick={() => logs(selectedRun)}>查看采集日志</button>
        {monitor ? <details><summary>查看完整关键采集事件</summary><MonitorDiagnostics monitor={monitor} /></details> : null}
      </section>
    </div>
  </ResponsiveDrawer></div>;
}
