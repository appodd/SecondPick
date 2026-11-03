import type { Monitor, MonitorPage } from "../../api/monitorClient";
import { monitorErrors, monitorPhases } from "../../api/monitorClient";
import type { ProjectOverview, Study, WindowMonitor } from "../../api/projectClient";
import type { MonitorTask } from "../../features/projects/monitorTasks";

export type StatusKind = "running" | "waiting" | "paused" | "success" | "attention" | "unknown" | "inactive" | "ready";
export interface StatusValue { kind: StatusKind; label: string; action?: string; reason?: string; updatedAt?: string | null }
export const unknownStatus = (reason = "后端尚未提供足够状态信息。 "): StatusValue => ({ kind: "unknown", label: "状态未知", reason });
export function serviceStatus(state: { label: string; tone: "good" | "warn" | "unknown"; detail: string; kind?: StatusKind }): StatusValue {
  return { kind: state.kind ?? (state.tone === "good" ? "ready" : state.tone === "warn" ? "attention" : "unknown"),
    label: state.label === "未知" ? "状态未知" : state.label, reason: state.detail };
}

export function monitorExecution(m?: Monitor, now = Date.now()): StatusValue {
  if (!m) return unknownStatus();
  const updatedAt = m.updated_at;
  if (m.state === "running") return { kind: "running", label: "正在采集", updatedAt,
    action: m.desired_state === "stopped" ? "正在停止监控并保存已采集数据" : m.desired_state === "paused" ? "正在暂停采集并保存数据"
      : m.result.worker_status?.phase === "completed" ? "采集程序已返回，等待本轮结算"
      : m.result.worker_status?.phase === "collecting" ? "正在执行已确认的采集范围；当前页及商品进度未提供"
      : monitorPhases[m.result.worker_status?.phase ?? ""] ?? "正在执行采集，细分动作未提供" };
  if (m.state === "needs_attention" || (m.error_code && m.error_code !== "cancelled")) return { kind: "attention", label: "采集需要处理", updatedAt,
    reason: monitorErrors[m.error_code ?? ""] ?? `后端报告异常${m.error_code ? `：${m.error_code}` : "，请查看运行记录"}` };
  if (m.state === "waiting") {
    const planned = m.next_run_at && /(?:Z|[+-]\d{2}:\d{2})$/i.test(m.next_run_at) ? Date.parse(m.next_run_at) : NaN;
    return { kind: "waiting", label: "等待下一轮", updatedAt,
      action: Number.isFinite(planned) ? planned > now ? "等待计划时间（按本机时钟）；当前没有采集执行" : "计划时间已到，等待后端调度（按本机时钟）" : "当前没有采集执行，等待原因暂不可确认",
      reason: "后端未提供资源占用或排队原因；不能据其他项目正在采集就判断正在等待其完成。计划时间不保证实际启动时间，本机与服务端可能存在时钟差异。" };
  }
  if (m.state === "paused") return { kind: "paused", label: "采集已暂停", updatedAt, reason: "后端已暂停本监控；当前没有采集执行。" };
  if (m.state === "stopped") return { kind: "inactive", label: "监控已停止", updatedAt, reason: "当前没有采集执行；停止本身不代表成功完成。" };
  return unknownStatus(`无法识别后端监控状态：${m.state}`);
}

export function monitorScheduling(m?: Monitor): StatusValue {
  if (!m) return unknownStatus();
  if (m.desired_state) return { kind: "waiting", label: m.desired_state === "stopped" ? "已请求停止监控" : "已请求暂停监控", reason: "当前采集退出前，操作尚未完成。" };
  if (["running", "waiting"].includes(m.state)) return { kind: "ready", label: "监控调度已启用", reason: "启用不代表此刻正在执行。" };
  if (m.state === "paused") return { kind: "paused", label: "监控调度已暂停", reason: m.error_code ? "后端报告暂停及异常；不将其视为用户主动暂停。" : "具体暂停来源未提供。" };
  if (m.state === "needs_attention") return { kind: "attention", label: "监控调度需处理" };
  if (m.state === "stopped") return { kind: "inactive", label: "监控调度已停止" };
  return unknownStatus();
}

export function monitorTaskExecution(task: MonitorTask): StatusValue {
  const status = monitorExecution(task.monitor);
  if (task.monitor?.state !== "stopped" || status.kind !== "inactive") return status;
  if (task.window?.mode === "once") return { ...status, label: "本次范围已结束", reason: "单次执行范围已经结束；现有结束字段不能单独证明本轮成功。" };
  if (task.window?.mode === "timed" || task.window?.mode === "ongoing") return { ...status, label: "调度已停止", reason: "本监控调度已停止；历史执行的结果请查看对应轮次。" };
  return { ...status, label: "监控已停止" };
}

/** All native project monitors, including monitors without a workspace execution window. */
export function projectMonitorExecution(page?: MonitorPage): StatusValue {
  if (!page) return unknownStatus("尚未取得本项目的采集执行状态。");
  if (!page.items.length) return { kind: "inactive", label: "尚无监控", reason: "引擎启用不等于已创建或正在执行监控。" };
  const statuses = page.items.map(item => monitorExecution(item));
  const active = statuses.find(status => status.kind === "running");
  if (active) return active;
  if (page.items.length >= 50) return unknownStatus("监控接口仅返回最近50条，无法排除更早的活动监控。");
  for (const kind of ["running", "unknown", "attention"] as const) {
    const value = statuses.find(status => status.kind === kind);
    if (value) return value;
  }
  if (!page.enabled || page.platform_enabled === false) return { kind: "inactive", label: "采集未启用", reason: "后端未启用采集服务或闲鱼平台；不会据历史监控推断当前执行。" };
  const waiting = statuses.find(status => status.kind === "waiting");
  if (waiting) return waiting;
  const paused = statuses.find(status => status.kind === "paused");
  if (paused) return { ...paused, reason: "当前没有采集执行；已有监控处于暂停，其余可能已停止。" };
  return statuses[0];
}

export function windowStatus(run: WindowMonitor["runs"][number], monitor?: Monitor): StatusValue {
  if (run.state === "running") return { kind: "waiting", label: "执行窗口有效", reason: monitor?.state === "waiting" ? "等待下一轮采集；窗口有效不代表采集正在执行。" : "实际采集状态以监控执行信息为准。" };
  if (run.state === "completed") return { kind: "inactive", label: "执行窗口已结束", updatedAt: run.finished_at, reason: "该字段也可能由手动停止产生，不能单独确认采集成功。" };
  if (run.state === "expired") return { kind: "inactive", label: "执行窗口已到期", updatedAt: run.finished_at };
  if (run.state === "stopped") return { kind: "inactive", label: "执行窗口已停止", updatedAt: run.finished_at };
  if (run.state === "paused") return { kind: "paused", label: "执行窗口已暂停" };
  if (run.state === "failed" && run.error === "cancelled") return { kind: "inactive", label: "执行窗口已中止", reason: "后端报告取消，不将取消当成成功。", updatedAt: run.finished_at };
  if (run.state === "failed") return { kind: "attention", label: "执行窗口需要处理", reason: run.error ?? "请检查采集错误与运行记录。", updatedAt: run.finished_at };
  return unknownStatus(`未识别的窗口状态：${run.state}`);
}

export function studyStatus(study: Study): StatusValue {
  if (study.state === "running") return { kind: "running", label: "研究正在执行", action: `正在执行研究任务 #${study.id}；细分阶段未提供` };
  if (study.state === "queued") return { kind: "waiting", label: "研究任务排队中", reason: "已受理，尚未开始执行。" };
  if (study.state === "superseded") return { kind: "inactive", label: study.error?.includes("证据") ? "证据已更新 · 本次未执行" : "目标已变更 · 本次未执行", reason: study.error ?? "旧版自动校准已跳过，快照保留。", updatedAt: study.finished_at };
  if (study.state === "completed") return { kind: "success", label: "本次研究已完成", updatedAt: study.finished_at };
  if (study.state === "failed") return { kind: "attention", label: "本次研究需要处理", reason: study.error ?? "研究执行失败，请查看错误信息。", updatedAt: study.finished_at };
  return unknownStatus(`未识别的研究状态：${study.state}`);
}

export function researchScheduling(data: ProjectOverview): StatusValue {
  if (![0, 1].includes(data.policy.paused) || ![0, 1].includes(data.policy.auto_research)) return unknownStatus("研究调度配置不完整，无法确认自动研究是否启用。");
  if (data.policy.completed || data.project.status === "completed") return { kind: "inactive", label: "项目研究调度已结束" };
  if (data.policy.paused) return { kind: "paused", label: "研究调度已暂停", reason: "不会启动本项目后续研究；已经运行的任务仍可保存结果。" };
  if (!data.policy.auto_research) return { kind: "inactive", label: "自动研究未启用", reason: "可手动提交研究；恢复调度不会授予自动研究权限。" };
  if (data.research_work?.gate === "failed") return { kind: "attention", label: "自动研究需处理", reason: data.research_work.reason };
  if (data.studies.some(study => study.state === "failed" && ["initial", "incremental"].includes(study.kind) && (!data.goal_context || study.goal_revision === data.goal_context.current_revision))) return { kind: "attention", label: "自动研究需处理", reason: "当前目标存在失败研究，后端会阻止新的自动入队；可检查并重试原快照。" };
  return { kind: "ready", label: "自动研究已启用", reason: "启用不代表此刻正在执行。" };
}

export function researchExecution(data: ProjectOverview): StatusValue {
  const running = data.studies.filter(study => study.state === "running");
  if (running.length) return studyStatus(running[0]);
  if (data.studies.length >= 30) return unknownStatus("接口仅返回最近 30 次研究，未见正在执行的任务；不能排除更早的活动任务。");
  const schedule = researchScheduling(data);
  if (schedule.kind === "unknown") return schedule;
  if (schedule.kind === "attention") return { ...schedule, label: "本项目研究需要处理" };
  if (schedule.kind === "paused" || data.policy.completed || data.project.status === "completed") return { ...schedule, action: "本项目当前没有正在执行的研究任务" };
  const queued = data.studies.filter(study => study.state === "queued").length;
  if (!queued && (data.phase === "initial_running" || data.coverage.under_ai > 0)) return unknownStatus("覆盖信息或研究阶段提示存在活动任务，但执行列表未提供对应记录；等待重新确认。");
  if (queued) return { kind: "waiting", label: "等待研究任务执行", reason: `${queued} 个研究任务已排队，等待后端执行；具体等待原因未提供。` };
  if (!data.policy.auto_research) return { kind: "waiting", label: "本项目研究当前空闲", reason: "自动研究未启用，可手动提交研究。" };
  if (data.integration_work?.state === "failed" || data.evidence_work?.items.some(item => item.state === "failed")) return { kind: "attention", label: "新证据研究需要处理", reason: data.integration_work?.state === "failed" ? data.integration_work.reason : "有限复评失败，不自动重试；请查看原研究任务。" };
  if (data.evidence_work?.listing_ids.length) return { kind: "waiting", label: "本项目研究当前空闲", reason: data.evidence_work.reason };
  if (data.research_work) return { kind: data.research_work.counts.failed && !data.research_work.counts.ready ? "attention" : "waiting",
    label: data.research_work.counts.failed && !data.research_work.counts.ready ? "有限补研需要处理" : "本项目研究当前空闲",
    reason: data.research_work.reason };
  return { kind: "waiting", label: "本项目研究当前空闲", reason: !data.total ? "等待商品样本。" : !data.report && data.eligible < data.policy.minimum
    ? "等待可比较样本或后端最长等待条件；准确触发时间未提供。" : "等待新一批研究触发条件，或手动提交研究。" };
}

export function productResearchStatus(state: string): StatusValue {
  const values: Record<string, StatusValue> = {
    waiting: { kind: "waiting", label: "待研究" }, queued: { kind: "waiting", label: "已纳入研究任务" },
    under_ai: { kind: "waiting", label: "已纳入研究任务（含排队）" },
    evaluated: { kind: "success", label: "已逐项分析" }, summarized: { kind: "success", label: "批次已概述" },
    rule_excluded: { kind: "inactive", label: "规则初筛排除" }, needs_information: { kind: "waiting", label: "信息待补充" },
    blocked: { kind: "attention", label: "商品研究受阻" },
  };
  return values[state] ?? unknownStatus();
}
