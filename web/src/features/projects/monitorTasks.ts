import type { Monitor } from "../../api/monitorClient";
import type { WindowMonitor } from "../../api/projectClient";

export interface MonitorTask { id: number; name: string; monitor?: Monitor; window?: WindowMonitor; source: "workspace" | "native" }
export function monitorTasks(windows: WindowMonitor[], native: Monitor[], windowsKnown: boolean): MonitorTask[] {
  const items: MonitorTask[] = windows.map(window => ({ id: window.monitor_id, name: window.name, monitor: window.monitor, window, source: "workspace" }));
  const ids = new Set(items.map(item => item.id));
  // Do not classify a task as legacy when workspace metadata could not be read.
  if (windowsKnown) for (const monitor of native) if (!ids.has(monitor.id)) items.push({ id: monitor.id, name: monitor.keyword, monitor, source: "native" });
  return items.sort((a, b) => b.id - a.id);
}
export function monitorMode(task: MonitorTask) {
  return task.window ? ({ once: "单次采集", timed: "限时监控", ongoing: "长期定时" }[task.window.mode] ?? "模式未知")
    : task.monitor?.max_rounds === 1 ? "单次采集" : "定时采集范围";
}
export function monitorCycle(task: MonitorTask) {
  if (task.window?.mode === "once" || task.monitor?.max_rounds === 1) return "采集一轮后结束";
  const seconds = task.monitor?.interval_seconds;
  return seconds && Number.isFinite(seconds) ? `每 ${seconds / 60} 分钟检查` : "周期未提供";
}
/** Paused future windows are resumable; ended windows require the original explicit rerun action. */
export function monitorStartAction(task: MonitorTask): "resume" | "rerun" | null {
  const monitor = task.monitor;
  if (!monitor || monitor.desired_state || !["paused", "stopped", "needs_attention"].includes(monitor.state)) return null;
  if (task.window) {
    if (task.window.mode === "once" && monitor.rounds >= monitor.max_rounds) return "rerun";
    return task.window.runs.some(run => ["running", "paused"].includes(run.state)) ? "resume" : "rerun";
  }
  return "resume";
}
export function startLabel(task: MonitorTask) {
  return monitorStartAction(task) === "rerun" ? task.window?.mode === "once" ? "重新采集" : "重新启动监控" : task.window?.mode === "once" || task.monitor?.state === "stopped" ? "继续采集" : "恢复监控";
}

export function canToggleMonitor(task: MonitorTask) {
  return !!task.window && ["ongoing", "timed"].includes(task.window.mode)
    && task.window.runs.some(run => ["running", "paused"].includes(run.state))
    && !!task.monitor && ["running", "waiting", "paused"].includes(task.monitor.state);
}
