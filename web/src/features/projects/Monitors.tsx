import {AutoCoverCache} from './AutoCoverCache';
import { useRef, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { projectApi, type WindowMonitor } from "../../api/projectClient";
import { monitorApi, monitorErrors, type Monitor } from "../../api/monitorClient";
import { MonitorCreator } from "./MonitorCreator";
import { Panel, date } from "./projectUi";
import { MonitorLogDetail } from "./MonitorLogDetail";
import { MonitorTaskDetail } from "./MonitorTaskDetail";
import { MonitorTaskActions } from "./MonitorTaskActions";
import { monitorCycle, monitorMode, monitorTasks, type MonitorTask } from "./monitorTasks";
import { SnapshotNotice, StatusBadge, StatusSnapshot, useExecutionStatus } from "../../components/status/ExecutionStatus";
import { monitorExecution, monitorScheduling, monitorTaskExecution } from "../../components/status/statusModel";
import { useMonitorEvents } from "../monitor/MonitorWorkspace";
import "./monitor-tasks.css";
import { useEntryHref } from "./contextNavigation";


function positiveId(value: string | null) { const id = value && /^[1-9]\d*$/.test(value) ? Number(value) : NaN; return Number.isSafeInteger(id) ? id : undefined; }
export function Monitors({ id }: { id: number; action?: (fn: () => Promise<unknown>) => Promise<void>; busy?: boolean }) {
  const entry = useEntryHref(id);

  const [editing, setEditing] = useState<WindowMonitor>();
  const rowButtons = useRef(new Map<string, HTMLButtonElement>());
  const [params, setParams] = useSearchParams();
  const query = useQuery({ queryKey: ["project", id, "monitors"], queryFn: () => projectApi.monitors(id), refetchInterval: 3000 });
  const native = useQuery({ queryKey: ["monitors", id], queryFn: () => monitorApi.list(id), refetchInterval: 3000 });
  const tasks = monitorTasks(query.data?.items ?? [], native.data?.items ?? [], query.isSuccess);
  const detailId = positiveId(params.get("monitor")), logId = positiveId(params.get("logs")), runId = positiveId(params.get("run"));
  const selected = tasks.find(task => task.id === (logId ?? detailId));
  const unavailable = (value: typeof query | typeof native) => value.isError || value.failureCount > 0 || value.fetchStatus === "paused";
  function snapshot(task: MonitorTask) { const source = task.source === "workspace" ? query : native; return { observedAt: source.dataUpdatedAt, unavailable: unavailable(source) }; }
  function update(values: Record<string, string | undefined>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) if (value === undefined) next.delete(key); else next.set(key, value);
    setParams(next, { replace: true });
  }
  function detail(task: MonitorTask) { update({ monitor: String(task.id), logs: undefined, logRound: undefined, run: undefined }); }
  function logs(task: MonitorTask, run?: number) { update({ logs: String(task.id), run: run ? String(run) : undefined, logRound: undefined }); }
  function closeDetail() {
    const previous = detailId;
    update({ monitor: undefined, run: undefined });
    requestAnimationFrame(() => rowButtons.current.get(`detail:${previous}`)?.focus({ preventScroll: true }));
  }
  function closeLogs() {
    const previous = logId;
    update({ logs: undefined, logRound: undefined, ...(detailId ? {} : { run: undefined }) });
    requestAnimationFrame(() => {
      if (detailId) document.querySelector<HTMLElement>('.mt-detail [data-open-logs]')?.focus({ preventScroll: true });
      else rowButtons.current.get(`logs:${previous}`)?.focus({ preventScroll: true });
    });
  }
  const summarySnapshot = { observedAt: Math.min(query.dataUpdatedAt, native.dataUpdatedAt), unavailable: unavailable(query) || unavailable(native) };
  return <>
    {params.get("proposal") ? <Panel className="sp-notice"><details><summary>有待审查的长期监控变更 · 尚未执行</summary><p>{params.get("proposal")}</p><p>选择目标任务，先暂停并等待采集退出，再编辑草案。只有预览并明确确认后才保存。</p></details></Panel> : null}
    <Panel className="mt-list-panel">
      <div className="sp-between"><h2>运行与执行记录</h2><span className="mt-task-count">{query.isSuccess && native.isSuccess ? "" : "已读取 "}{tasks.length} 个任务</span></div>
      <div className="mt-toolbar"><StatusSnapshot {...summarySnapshot}><TaskSummary tasks={tasks} /></StatusSnapshot></div>
      {native.data && (!native.data.enabled || native.data.platform_enabled === false) ? <p className="sp-muted">当前服务未启用采集或闲鱼平台，已有任务与日志仍可查看。</p> : null}
      {query.isLoading || native.isLoading ? <p role="status">正在读取真实任务…</p> : null}
      {query.error ? <p role="alert" className="sp-error">工作区任务暂不可读取。{query.error.message}<button onClick={() => void query.refetch()}>重试工作区任务</button></p> : null}
      {native.error ? <p role="alert" className="sp-error">原有监控暂不可读取，任务列表可能不完整。<button onClick={() => void native.refetch()}>重试原有监控</button></p> : null}
      <div className="mt-task-list" aria-label="监控任务列表">{tasks.map(task => <StatusSnapshot key={task.id} {...snapshot(task)}>
        <article className="mt-task-row" aria-label={`监控任务 ${task.name}`}>
          <div className="mt-row-heading"><button className="mt-task-name" ref={node => { if (node) rowButtons.current.set(`detail:${task.id}`, node); }} onClick={() => detail(task)}>{task.name}</button><StatusBadge status={monitorScheduling(task.monitor)} live /></div>
          <p className="mt-keyword">关键词：{task.monitor?.keyword ?? "当前数据未提供"}</p>
          <div className="mt-row-meta"><span>{monitorMode(task)} · {monitorCycle(task)}</span><StatusBadge status={monitorTaskExecution(task)} live />{task.monitor ? <span>已尝试 {task.monitor.rounds} 轮采集</span> : null}</div>
          {task.monitor ? <MonitorRecentRun monitor={task.monitor} /> : <p className="sp-muted">监控数据不完整，操作暂不可用。</p>}
          {task.monitor && Object.keys(task.monitor.result).length ? <dl className="mt-outcome" aria-label="最近一次采集结果"><div><dt>本轮搜索记录</dt><dd>{task.monitor.result.search_cards?.imported ?? "—"}</dd></div><div><dt>详情采集成功</dt><dd>{task.monitor.result.collection?.raw_saved ?? "—"}</dd></div><div><dt>当时商品库</dt><dd>{task.monitor.result.candidate_pool_count ?? "—"}</dd></div></dl> : null}
          {task.monitor?.error_code ? <p role="status" className="sp-muted">{monitorErrors[task.monitor.error_code] ?? "本轮未完成，请查看采集日志。"}</p> : null}
          <div className="mt-row-actions"><button onClick={() => detail(task)}>查看详情</button><button ref={node => { if (node) rowButtons.current.set(`logs:${task.id}`, node); }} disabled={!task.monitor} onClick={() => logs(task)}>查看采集日志</button><MonitorTaskActions task={task} projectId={id} compact /></div>
        </article>
      </StatusSnapshot>)}</div>
      {query.isSuccess && native.isSuccess && !tasks.length ? <div className="mt-empty"><h3>还没有监控任务</h3><p>创建草案并确认后才启动采集。</p></div> : null}
      <details className="mt-source-note"><summary>数据状态与兼容入口</summary><StatusSnapshot {...summarySnapshot}><SnapshotNotice /></StatusSnapshot><p>已入库商品的 Agent 研究独立继续。执行窗口和采集器轮次分别保存，不能混用编号。</p><Link to={entry(`/tasks/${id}?tab=monitor`)}>查看原有范围管理与采集诊断 ↗</Link></details>
    </Panel>
    <AutoCoverCache taskId={id}/>
    {(logId ?? detailId) && !selected && query.isSuccess && native.isSuccess ? <Panel><p role="status">该监控未在当前项目的已读取任务中找到。</p><button onClick={() => update({ monitor: undefined, logs: undefined, run: undefined, logRound: undefined })}>返回任务列表</button></Panel> : null}
    {selected && !editing ? <StatusSnapshot {...snapshot(selected)}>{logId && selected.monitor ? <MonitorLogDetail task={selected} selectedRun={runId}
      initialRound={/^[0-9a-f]{32}$/.test(params.get("logRound") ?? "") ? params.get("logRound")! : ""}
      roundChanged={round => update({ logRound: round || undefined })} close={closeLogs} /> : detailId ? <MonitorTaskDetail task={selected} projectId={id} selectedRun={runId}
      selectRun={run => update({ run: String(run) })} logs={run => logs(selected, run)} edit={() => setEditing(selected.window)} close={closeDetail} /> : null}</StatusSnapshot> : null}
    {editing ? <MonitorCreator id={id} goal={params.get("proposal") ?? editing.monitor.keyword} existing={editing} close={() => setEditing(undefined)} saved={async () => { setEditing(undefined); await query.refetch(); await native.refetch(); }} /> : null}
  </>;
}

function TaskSummary({ tasks }: { tasks: MonitorTask[] }) {
  const status = useExecutionStatus({ kind: "ready", label: "已读取" });
  if (status.kind === "unknown" || tasks.some(task => monitorExecution(task.monitor).kind === "unknown")) return <p className="mt-summary" role="status">状态暂不可确认 · 等待重新确认完整任务状态</p>;
  const enabled = tasks.filter(task => monitorScheduling(task.monitor).kind === "ready").length;
  const running = tasks.filter(task => monitorExecution(task.monitor).kind === "running").length;
  return <p className="mt-summary"><span>{enabled} 个调度启用</span><span>{running} 个正在采集</span><span>{tasks.reduce((total, task) => total + (task.window?.runs.length ?? 0), 0)} 次已记录执行窗口</span></p>;
}
function MonitorRecentRun({ monitor }: { monitor: Monitor }) {
  const events = useMonitorEvents(monitor);
  const recent = events.data?.pages.flatMap(page => page.items).find(item => ["round_started", "round_finished"].includes(item.code));
  return <div className="mt-recent"><span>{recent ? `${recent.code === "round_started" ? "最近采集开始" : "最近一轮结束"}：${date(recent.created_at)}` : `最近状态更新：${date(monitor.updated_at)}`}</span>
    {events.error ? <span>执行事件暂不可刷新；已保存记录不代表当前执行。</span> : null}</div>;
}
