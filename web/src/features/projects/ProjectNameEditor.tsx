import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { conversationClient } from "../../api/conversationClient";
import type { TaskListResponse } from "../../api/types";
import type { ProjectOverview } from "../../api/projectClient";

export function ProjectNameEditor({ id, title, close }: { id: number; title: string; close: () => void }) {
  const cache = useQueryClient(), input = useRef<HTMLInputElement>(null), form = useRef<HTMLFormElement>(null);
  const busy = useRef(false), composing = useRef(false);
  const [value, setValue] = useState(title), [saving, setSaving] = useState(false), [error, setError] = useState("");
  useEffect(() => { input.current?.focus(); input.current?.select(); }, []);
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (!busy.current && event.target instanceof Node && !form.current?.contains(event.target)) close(); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [close]);
  async function save() {
    if (busy.current || composing.current) return;
    const name = value.trim();
    if (!name) { setError("名称不能为空"); return; }
    if (name === title) { close(); return; }
    busy.current = true; setSaving(true); setError("");
    try {
      const updated = await conversationClient.renameTask(id, name);
      const updateList = (old?: TaskListResponse) => old ? { ...old, items: old.items.map(t => t.id === id ? { ...t, title: updated.title, updated_at: updated.updated_at } : t) } : old;
      cache.setQueriesData<TaskListResponse>({ queryKey: ["projects", "list"] }, updateList);
      cache.setQueriesData<TaskListResponse>({ queryKey: ["workspace", "runtime-projects"] }, updateList);
      cache.setQueryData<ProjectOverview>(["project", id], old => old ? { ...old, project: { ...old.project, title: updated.title } } : old);
      void cache.invalidateQueries({ queryKey: ["projects", "list"] });
      void cache.invalidateQueries({ queryKey: ["project", id] });
      close();
    } catch {
      setError("保存未成功，请重试；可按 Esc 取消");
      requestAnimationFrame(() => input.current?.focus());
    } finally { busy.current = false; setSaving(false); }
  }
  return <form className="sp-project-name-editor" ref={form} aria-label="重命名选购项目" onSubmit={e => { e.preventDefault(); void save(); }} onBlur={e => { if (!busy.current && !e.currentTarget.contains(e.relatedTarget)) close(); }}>
    <input ref={input} aria-label="项目名称" aria-invalid={!!error} aria-describedby={error ? `project-name-error-${id}` : undefined} maxLength={60} value={value} disabled={saving}
      onChange={e => { setValue(e.target.value); setError(""); }} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
      onKeyDown={e => { if (e.key === "Escape" && !busy.current) { e.preventDefault(); e.stopPropagation(); close(); } if (e.key === "Enter" && (composing.current || e.nativeEvent.isComposing || e.keyCode === 229)) e.preventDefault(); }}/>
    {error ? <small role="alert" id={`project-name-error-${id}`}>{error}</small> : <small role={saving ? "status" : undefined}>{saving ? "正在保存…" : "Enter 保存 · Esc 取消"}</small>}
  </form>;
}
