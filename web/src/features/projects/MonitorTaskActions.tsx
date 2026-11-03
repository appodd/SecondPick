import { Pause, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import { monitorApi } from "../../api/monitorClient";
import { projectApi } from "../../api/projectClient";
import { useExecutionStatus } from "../../components/status/ExecutionStatus";
import { monitorExecution } from "../../components/status/statusModel";
import { canToggleMonitor, monitorStartAction, startLabel, type MonitorTask } from "./monitorTasks";
import { useEntryHref } from "./contextNavigation";

export function MonitorTaskActions({ task, projectId, compact = false }: { task: MonitorTask; projectId: number; compact?: boolean }) {
  const cache = useQueryClient();
  const entry = useEntryHref(projectId);
  const [pendingAction, setPendingAction] = useState<"pause" | "stop" | "resume" | "rerun" | null>(null);
  const submitting = useRef(false);
  const pending = pendingAction !== null;
  const [error, setError] = useState("");
  const [loginHelp, setLoginHelp] = useState(false);
  const [feedback, setFeedback] = useState("");
  const status = useExecutionStatus(monitorExecution(task.monitor));
  const monitor = task.monitor;
  if (!monitor) return null;
  const fresh = status.kind !== "unknown";
  const start = monitorStartAction(task);
  const exhausted = start === "resume" && monitor.rounds >= monitor.max_rounds;
  const toggle = canToggleMonitor(task);
  const enabled = ["running", "waiting"].includes(monitor.state);
  const switchLabel = !fresh ? "监控状态待确认" : monitor.desired_state === "stopped" || pendingAction === "stop" ? "正在停止监控…"
    : monitor.desired_state || pendingAction === "pause" ? "正在暂停监控…"
    : pendingAction === "resume" ? "正在开启监控…" : enabled ? "监控已开启" : "监控已暂停";
  const unavailableReason = !fresh ? "当前状态尚未确认，请先查看详情或等待刷新。" : monitor.desired_state ? "正在等待当前采集退出，请稍后再操作。" : exhausted ? "已用完原确认轮次，请在新建监控中确认新的采集范围。" : null;
  async function control(action: "pause" | "stop" | "resume" | "rerun") {
    if (submitting.current) return;
    if (action === "rerun" && task.window?.mode === "once" && !window.confirm(`重新采集将按当前范围搜索“${monitor!.keyword}”，最多 ${monitor!.max_pages} 页、${monitor!.max_items} 件商品${monitor!.collect_seller_profiles ? '，包含卖家资料采集' : ''}。\n将新建一轮执行，已有商品和历史记录保留。是否开始？`)) return;
    submitting.current = true;
    setPendingAction(action); setError(""); setLoginHelp(false); setFeedback("");
    try {
      if (action === "rerun") await projectApi.rerun(projectId, task.id);
      else {
        const result = await monitorApi.control(projectId, task.id, action);
        const state = monitorExecution(result);
        setFeedback(state.kind === "unknown" ? "请求已返回，但当前状态暂不可确认；正在重新读取。" : result.desired_state ? "请求已受理，正在等待当前采集退出；尚未完成暂停或停止。" : action === "resume" ? "恢复请求已受理，执行状态以上方记录为准。" : `后端已确认：${state.label}。`);
      }
      await Promise.all([cache.invalidateQueries({ queryKey: ["project", projectId] }), cache.invalidateQueries({ queryKey: ["monitors", projectId] })]);
      if (action === "rerun") setFeedback("再次运行请求已受理，请查看重新读取的执行窗口与采集状态。");
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : String(failure);
      setError(message);
      setLoginHelp(failure instanceof ApiError && ['login_required','verification_required'].includes(failure.code) || /请先.*(?:登录闲鱼|验证闲鱼登录)/.test(message));
    }
    finally { submitting.current = false; setPendingAction(null); }
  }
  return <div className="mt-controls">
    <div className="sp-actions">
        {toggle ? <div className="mt-monitor-switch-control">
          <button type="button" className="mt-monitor-switch" role="switch" aria-label="监控开关" aria-checked={enabled} aria-busy={pending || !!monitor.desired_state}
            title={unavailableReason ?? (enabled ? '暂停当前采集与后续调度，已有记录保留。' : '恢复后续调度，实际采集状态以上方记录为准。')}
            disabled={!fresh || pending || !!monitor.desired_state || (!enabled && exhausted)} onClick={() => {
              if (enabled && monitor.state === 'running' && !window.confirm('暂停监控会停止当前采集，并暂停后续调度。是否继续？')) return;
              void control(enabled ? 'pause' : 'resume');
            }}><span /></button>
          <span className="mt-monitor-switch-label" aria-live="polite">{switchLabel}</span>
        </div> : null}
        {!toggle && enabled ? <button title={task.window?.mode === 'once' ? '暂停会中止当前采集，已有记录会保留。' : '暂停会中止当前采集，并暂停后续调度。'} disabled={!fresh || pending || !!monitor.desired_state} onClick={() => {
          if (toggle && monitor.state === 'running' && !window.confirm('暂停监控会停止当前采集，并暂停后续调度。是否继续？')) return;
          void control('pause');
        }}><Pause size={13}/>{task.window?.mode === 'once' ? '暂停采集' : '暂停监控'}</button> : null}
        {!toggle && start ? <button className="mt-restart-action" title={unavailableReason ?? undefined} disabled={!fresh || pending || exhausted} onClick={() => void control(start)}><RotateCcw size={13}/>{startLabel(task)}</button> : null}
      {!compact && monitor.state !== "stopped" ? <button disabled={!fresh || pending || !!monitor.desired_state} onClick={() => void control("stop")}>停止监控（含当前采集）</button> : null}
    </div>
    {pending ? <p role="status">正在提交操作，实际状态以后端返回为准…</p> : null}
    {!pending && feedback ? <p role="status">{feedback}</p> : null}
    {unavailableReason ? <p className="sp-muted" role="note">{unavailableReason}</p> : null}
    {error ? <p role="alert" className="sp-error">{error}{loginHelp ? <Link className="mt-error-link" to={entry('/settings?section=xianyu')}>前往闲鱼账户设置 →</Link> : null}</p> : null}
  </div>;
}
