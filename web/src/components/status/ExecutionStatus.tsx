import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { LoaderCircle, Clock3, PauseCircle, CheckCircle2, CircleAlert, CircleHelp, CircleStop, CircleMinus } from "lucide-react";
import type { StatusKind, StatusValue } from "./statusModel";
import "./status.css";

interface Snapshot { observedAt: number; unavailable: boolean; now: number; staleAfterMs: number }
const SnapshotContext = createContext<Snapshot | null>(null);
function statusTime(value: string) { return Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未提供有效时间"; }
export function StatusSnapshot({ observedAt, unavailable = false, staleAfterMs = 15_000, children }: {
  observedAt: number; unavailable?: boolean; staleAfterMs?: number; children: ReactNode;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const update = () => setNow(Date.now());
    const timer = setInterval(update, 3000);
    window.addEventListener("focus", update); document.addEventListener("visibilitychange", update);
    return () => { clearInterval(timer); window.removeEventListener("focus", update); document.removeEventListener("visibilitychange", update); };
  }, []);
  return <SnapshotContext.Provider value={{ observedAt, unavailable, staleAfterMs, now }}>{children}</SnapshotContext.Provider>;
}

export function snapshotStatus(status: StatusValue, snapshot: Snapshot | null): StatusValue {
  if (!snapshot) return status;
  if (snapshot.unavailable || !snapshot.observedAt || snapshot.now - snapshot.observedAt > snapshot.staleAfterMs) {
    return { kind: "unknown", label: "状态暂不可确认", reason: snapshot.unavailable ? "状态读取失败；不能用上次数据确认当前执行状态。" : "状态信息已过期，等待重新读取。" };
  }
  return status;
}
export function useExecutionStatus(status: StatusValue, live = true) { const snapshot = useContext(SnapshotContext); return snapshotStatus(status, live ? snapshot : null); }
const icons: Record<StatusKind, typeof Clock3> = { running: LoaderCircle, waiting: Clock3, paused: PauseCircle, success: CheckCircle2,
  attention: CircleAlert, unknown: CircleHelp, inactive: CircleMinus, ready: CheckCircle2 };

export type SemanticTone = "positive" | "negative" | "caution" | "neutral";
export function StatusBadge({ status, live = false, className = "", tone }: { status: StatusValue; live?: boolean; className?: string; tone?: SemanticTone }) {
  const value = useExecutionStatus(status, live);
  const Icon = value.kind === "inactive" && /停止|已结束|已中止|已到期/.test(value.label) ? CircleStop : icons[value.kind];
  return <span className={`sp-status ${className}`} data-kind={value.kind} data-tone={value === status ? tone : undefined} title={value.reason}><Icon size={14} aria-hidden="true" />{value.label}</span>;
}
export function ExecutionStatus({ status, children }: { status: StatusValue; children?: ReactNode }) {
  const value = useExecutionStatus(status);
  return <section className="sp-execution" aria-label="当前执行状态"><div className="sp-execution-heading"><StatusBadge status={value} />{children}</div>
    {value.action ? <p className="sp-execution-action">{value.action}</p> : null}
    {value.reason ? <p className="sp-execution-reason">{value.reason}</p> : null}
    {value.updatedAt ? <p className="sp-status-time">最近状态更新：{statusTime(value.updatedAt)}</p> : null}
  </section>;
}
export function ProgressSummary({ completed, total, unit = "项", children }: { completed?: number; total?: number; unit?: string; children?: ReactNode }) {
  const measurable = Number.isFinite(completed) && Number.isFinite(total) && total! > 0 && completed! >= 0 && completed! <= total!;
  return <div className="sp-progress-summary">{children}{measurable ? <><span>已处理 {completed} / {total} {unit}</span><progress aria-label="已确认的执行进度" value={completed} max={total} /></> : null}</div>;
}
export function SnapshotNotice() {
  const data = useContext(SnapshotContext);
  if (!data) return null;
  const expired = data.unavailable || data.now - data.observedAt > data.staleAfterMs;
  return <p className="sp-status-time">{expired ? "当前状态暂不可确认 · " : "状态确认于 "}{data.observedAt ? new Date(data.observedAt).toLocaleTimeString("zh-CN", { hour12: false }) : "尚未取得数据"}。状态确认时间不是执行进展时间。</p>;
}
