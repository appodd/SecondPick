import { Link } from "react-router-dom";
import type { OperationDto } from "../../api/types";

const labels = { queued: "已排队，准备分析", running: "正在分析已有证据", waiting_confirmation: "等待确认采集请求", completed: "本次分析已完成", failed: "本次分析未完成", cancelled: "已停止，未保存不完整回答", interrupted: "服务重启，任务已中断。你可以重新发送消息。" };
const stages: Record<string, string> = { preparing_context: "正在整理任务上下文", starting_codex: "正在启动 Codex", analyzing_evidence: "正在分析已有证据", preparing_answer: "正在整理完整回答" };
export function OperationStatus({ operation, stage, reconnecting, onStop, stopping }: {
  operation: OperationDto; stage?: string; reconnecting?: boolean; onStop: () => void; stopping?: boolean;
}) {
  const active = operation.state === "queued" || operation.state === "running";
  return <div className={`operation-status operation-status--${operation.state}`} role="status" aria-live="polite">
    <span>{active && stage ? stages[stage] ?? labels[operation.state] : labels[operation.state]}</span>
    {reconnecting && active && <span className="muted">连接恢复中，分析仍在继续…</span>}
    {operation.state === "failed" && <p>{operation.error_detail} <Link to="/settings">检查设置</Link></p>}
    {active && <button onClick={onStop} disabled={stopping}>{stopping ? "停止中…" : "停止"}</button>}
  </div>;
}
