import { useEffect, useState, type ReactNode } from "react";
import { StatusBadge } from "./ExecutionStatus";
import type { StatusKind } from "./statusModel";
import "./ai-task-feedback.css";

export type AiFeedbackState = "working" | "success" | "error" | "notice";
/** Local HTTP work, not an inferred background AgentRun or synthetic progress. */
export function AiTaskFeedback({ state, title, description, children }: {
  state: AiFeedbackState; title: string; description?: string; children?: ReactNode;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (state !== "working") return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [state]);
  const kind: StatusKind = state === "working" ? "running" : state === "success" ? "success" : state === "error" ? "attention" : "waiting";
  const waiting = state === "working" && elapsed >= 45 ? "本次等待较久，尚未收到 AI 结果。你可以继续填写；手动修改会被保留。"
    : state === "working" && elapsed >= 15 ? "仍在等待 AI 返回，你可以继续编辑下方表单。" : description;
  return <section className="sp-ai-feedback" data-state={state} aria-label="AI 处理反馈">
    <div role={state === "error" ? "alert" : "status"} aria-live={state === "error" ? "assertive" : "polite"}>
      <StatusBadge status={{ kind, label: title }} />
      {waiting ? <p>{waiting}</p> : null}
    </div>
    {state === "working" ? <small aria-hidden="true">已等待 {elapsed} 秒 · 未提供进度与预计完成时间</small> : null}
    {children}
  </section>;
}
