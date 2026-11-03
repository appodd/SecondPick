import type { MonitorPage } from "../../api/monitorClient";
import type { ProjectOverview } from "../../api/projectClient";
import { projectMonitorExecution, researchExecution, unknownStatus, type StatusValue } from "../../components/status/statusModel";

export function workspaceMonitorStatus(page?: MonitorPage): StatusValue {
  const status = projectMonitorExecution(page);
  const labels: Record<string, string> = { running: "采集中", waiting: "采集等待", paused: "采集暂停", attention: "采集需处理", unknown: "采集未知" };
  return { ...status, label: labels[status.kind] ?? (!page?.items.length ? "尚无监控" : status.label === "采集未启用" ? "采集未启用" : "监控停止"), reason: status.action ?? status.reason };
}
export function workspaceResearchStatus(data?: ProjectOverview): StatusValue {
  const status = data ? researchExecution(data) : unknownStatus("本项目研究状态尚未读取。");
  const labels: Record<string, string> = { running: "AI 研究中", waiting: "AI 等待", paused: "AI 暂停", attention: "AI 需处理", unknown: "AI 状态未知", inactive: "AI 调度结束" };
  return { ...status, label: status.kind === "waiting" && data && !data.studies.some(study => study.state === "queued") ? "AI 空闲" : labels[status.kind] ?? status.label,
    reason: `${status.action ?? status.reason ?? status.label} 仅项目研究任务，不包含历史对话 Operation 或其他服务。` };
}
