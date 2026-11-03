import type { CandidatePage, TaskDetail } from "../../api/types";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";

export interface TaskHeaderProps {
  taskDetail?: TaskDetail;
  candidatePage?: CandidatePage;
}

export function TaskHeader({ taskDetail, candidatePage }: TaskHeaderProps) {
  if (!taskDetail) {
    return <header className="task-header"><p className="workspace-eyebrow">研究任务</p><h1 id="workspace-title">加载任务...</h1></header>;
  }
  return <header className="task-header">
    <p className="workspace-eyebrow">{taskDetail.task.city} · {taskDetail.task.status}</p>
    <TaskTitleEditor key={taskDetail.task.id} task={taskDetail.task} />
    <dl className="task-header__facts">
      <div><dt>候选</dt><dd>{candidatePage?.deduplicated_count ?? "-"}</dd></div>
      <div><dt>报告</dt><dd>{taskDetail.history_page?.total_counts.reports ?? taskDetail.reports.length}</dd></div>
      <div><dt>搜索覆盖</dt><dd>{taskDetail.search_coverage.status}</dd></div>
    </dl>
  </header>;
}

function TaskTitleEditor({ task }: { task: TaskDetail["task"] }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [savedTitle, setSavedTitle] = useState(task.title);
  const [validationError, setValidationError] = useState("");
  const baseline = useRef(task.title);
  const saving = useRef(false);
  useEffect(() => setSavedTitle(task.title), [task.title]);
  const rename = useMutation({
    mutationFn: (value: string) => api.renameTask(task.id, value),
    onSuccess: task => {
      client.setQueryData(["task", task.id], (previous: TaskDetail | undefined) => previous ? { ...previous, task } : previous);
      void client.invalidateQueries({ queryKey: ["tasks"] });
      setSavedTitle(task.title);
      setEditing(false);
    },
    onSettled: () => { saving.current = false; },
  });
  function commit() {
    if (saving.current) return;
    const normalized = title.trim();
    if (!normalized) { setValidationError("任务名称不能为空"); return; }
    if (normalized === baseline.current) { setEditing(false); rename.reset(); return; }
    saving.current = true;
    setValidationError("");
    rename.mutate(normalized);
  }
  function cancel() {
    if (saving.current) return;
    setEditing(false);
    setValidationError("");
    rename.reset();
  }
  return editing ? <form className="task-rename" onSubmit={event => { event.preventDefault(); commit(); }}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) commit(); }}
      onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); cancel(); } }}>
        <input aria-label="任务名称" autoFocus value={title} maxLength={60} disabled={rename.isPending}
          onChange={event => { setTitle(event.target.value); setValidationError(""); }} />
        <button type="submit" disabled={rename.isPending || !title.trim()}>保存</button>
        <button type="button" disabled={rename.isPending} onClick={cancel}>取消</button>
        <small className="task-rename__hint">{rename.isPending ? "正在保存…" : "Enter 保存 · Esc 取消 · 点击别处自动保存"}</small>
        {(rename.error || validationError) && <p role="alert" className="scoped-error">{validationError || rename.error?.message}</p>}
      </form> : <div className="task-rename"><h1 id="workspace-title">{savedTitle}</h1>
        <button aria-label="重命名任务" onClick={() => {
          baseline.current = savedTitle; setTitle(savedTitle); setValidationError(""); rename.reset(); setEditing(true);
        }}>重命名</button></div>;
}
