import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { TaskListItem, TaskListResponse } from "../../api/types";
import { api } from "../../api/client";
import { monitorApi, type MonitorPage } from "../../api/monitorClient";
import { projectApi, type ProjectOverview } from "../../api/projectClient";
import { ResponsiveDrawer } from "../../components/layout/ResponsiveDrawer";
import { ExecutionStatus, SnapshotNotice, StatusBadge, StatusSnapshot, useExecutionStatus } from "../../components/status/ExecutionStatus";
import { monitorExecution, monitorScheduling, projectMonitorExecution, researchExecution, researchScheduling, studyStatus } from "../../components/status/statusModel";
import { workspaceMonitorStatus, workspaceResearchStatus } from "./workspaceRuntimeModel";
import { date } from "./projectUi";
import "./workspace-runtime.css";
import { useEntryHref } from "./contextNavigation";
import { ProjectNameEditor } from "./ProjectNameEditor";

function useProjectRuntime(id: number) {
  const monitors = useQuery({ queryKey: ["monitors", id], queryFn: () => monitorApi.list(id), refetchInterval: 5000, staleTime: 3000 });
  const research = useQuery({ queryKey: ["project", id], queryFn: () => projectApi.overview(id), refetchInterval: 10000, staleTime: 5000 });
  return { monitors, research };
}
function ReadSnapshot({ query, children }: { query: { dataUpdatedAt: number; isError: boolean; failureCount: number; fetchStatus: string }; children: ReactNode }) {
  return <StatusSnapshot observedAt={query.dataUpdatedAt} unavailable={query.isError || query.failureCount > 0 || query.fetchStatus === "paused"}>{children}</StatusSnapshot>;
}
function ProjectLink({ task, active, returnHref }: { task: TaskListItem; active: number; returnHref?: string }) {
  const { monitors, research } = useProjectRuntime(task.id);
  const selected = active === task.id, [editing,setEditing] = useState(false), eligibleClick = useRef(selected);
  useEffect(()=>{if(!selected)setEditing(false)},[selected]);
  const badges = <span className="sp-project-runtime-badges">
      <ReadSnapshot query={monitors}><StatusBadge status={workspaceMonitorStatus(monitors.data)} live /></ReadSnapshot>
      <ReadSnapshot query={research}><StatusBadge status={workspaceResearchStatus(research.data)} live /></ReadSnapshot>
    </span>;
  if (editing && selected) return <div className="sp-project-renaming" data-runtime-project={task.id}><ProjectNameEditor id={task.id} title={task.title} close={()=>setEditing(false)}/>{badges}</div>;
  return <Link data-runtime-project={task.id} to={selected && returnHref ? returnHref : `/projects/${task.id}`} className={selected ? "active" : ""} aria-current={selected ? "page" : undefined} onKeyDown={e=>{if(selected&&e.key==='F2'){e.preventDefault();setEditing(true)}}}>
    <strong title={selected ? `${task.title} · 双击重命名（或按 F2）` : task.title} onMouseDown={e=>{if(e.detail===1)eligibleClick.current=selected}} onClick={e=>{if(selected&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey)e.preventDefault()}} onDoubleClick={e=>{if(selected&&eligibleClick.current){e.preventDefault();e.stopPropagation();setEditing(true)}}}>{task.title}</strong>{badges}
  </Link>;
}
export function ProjectRuntimeNavigation({ tasks, active, returnHref }: { tasks?: TaskListResponse; active: number; returnHref?: string }) {
  const [limit, setLimit] = useState(8);
  const listRef = useRef<HTMLDivElement>(null);
  const items = tasks?.items ?? [];
  const visible = items.slice(0, limit);
  const selected = items.find(task => task.id === active);
  if (selected && !visible.some(task => task.id === active)) visible[visible.length - 1] = selected;
  // Only a selection change (or its first arrival) reveals the item. Polling must not move the list.
  useLayoutEffect(() => {
    const list = listRef.current, item = list?.querySelector<HTMLElement>(`[data-runtime-project="${active}"]`);
    if (!list || !item || !list.clientHeight) return;
    const bounds = list.getBoundingClientRect(), target = item.getBoundingClientRect();
    if (target.top < bounds.top) list.scrollTop += target.top - bounds.top;
    else if (target.bottom > bounds.bottom) list.scrollTop += target.bottom - bounds.bottom;
  }, [active, selected?.id]);
  return <div className="sp-project-list" ref={listRef} role="region" aria-label="选购项目列表" tabIndex={0}>{visible.map(task => <ProjectLink key={task.id} task={task} active={active} returnHref={returnHref} />)}
    {items.length > limit ? <button className="sp-runtime-more" onClick={() => setLimit(limit + 8)}>显示更多项目（已显示 {visible.length} / {items.length}）</button> : null}
    {tasks?.truncated || tasks?.page?.has_more ? <p className="sp-runtime-note">项目列表尚未完整读取；全局概况可继续分页。</p> : null}
  </div>;
}
function MonitorDetails({ page, id }: { page?: MonitorPage; id: number }) {
  const entry = useEntryHref(id);
  const status = useExecutionStatus(projectMonitorExecution(page));
  if (status.kind === "unknown") return <ExecutionStatus status={status} />;
  const enabled = page?.items.filter(item => ["waiting", "running"].includes(item.state) && !item.desired_state).length ?? 0;
  return <><ExecutionStatus status={status} /><p className="sp-runtime-meta">{page!.items.length >= 50 ? "最近50条中至少 " : ""}{enabled} 个监控调度配置启用{!page!.enabled || page!.platform_enabled === false ? " · 采集服务或平台未启用" : ""}</p>
    <div className="sp-runtime-active">{page!.items.filter(item => ["running", "waiting", "paused", "needs_attention"].includes(item.state) || monitorExecution(item).kind === "attention").map(item => <div key={item.id}>
      <div className="sp-between"><Link to={entry(`/projects/${id}?view=monitors&monitor=${item.id}`)}>监控 #{item.id} · {item.keyword}</Link><StatusBadge status={monitorScheduling(item)} live /></div>
      <ExecutionStatus status={monitorExecution(item)} />
      {item.state === "waiting" ? <p>下轮计划：{date(item.next_run_at)}；具体资源等待原因未提供。</p> : null}
      {item.state === "running" ? <p>本摘要未返回精确采集轮次 ID；不把监控 ID 或有效窗口冒充正在执行的 MonitorRun。</p> : null}
    </div>)}</div><Link to={entry(`/projects/${id}?view=monitors`)}>查看项目监控 →</Link><SnapshotNotice /></>;
}
function ResearchDetails({ data, id }: { data?: ProjectOverview; id: number }) {
  const entry = useEntryHref(id);
  const status = useExecutionStatus(data ? researchExecution(data) : { kind: "unknown", label: "研究状态未知" });
  if (!data || status.kind === "unknown") return <ExecutionStatus status={status} />;
  return <><StatusBadge status={researchScheduling(data)} live /><ExecutionStatus status={status} />
    <div className="sp-runtime-active">{data.studies.filter(study => ["running", "queued"].includes(study.state)).map(study => <div key={study.id}><Link to={entry(`/projects/${id}?view=research#research-run-${study.id}`)}>AgentRun #{study.id}</Link><StatusBadge status={studyStatus(study)} live /></div>)}</div>
    {data.studies.length >= 30 ? <p>只返回最近30次研究，无法保证完整活动任务范围。</p> : null}
    <Link to={entry(`/projects/${id}?view=research`)}>查看研究与异常记录 →</Link><SnapshotNotice /></>;
}
function RuntimeProject({ task }: { task: TaskListItem }) {
  const entry = useEntryHref(task.id);
  const { monitors, research } = useProjectRuntime(task.id);
  return <section className="sp-runtime-project" aria-label={`${task.title} 运行概况`}><h3><Link to={entry(`/projects/${task.id}`)}>{task.title}</Link></h3><div className="sp-runtime-columns">
    <section aria-label="项目采集状态"><h4>监控与采集</h4><ReadSnapshot query={monitors}><MonitorDetails page={monitors.data} id={task.id} /></ReadSnapshot>{monitors.isError ? <button onClick={() => void monitors.refetch()}>重读采集状态</button> : null}</section>
    <section aria-label="项目研究状态"><h4>项目 Agent 研究</h4><ReadSnapshot query={research}><ResearchDetails data={research.data} id={task.id} /></ReadSnapshot>{research.isError ? <button onClick={() => void research.refetch()}>重读研究状态</button> : null}</section>
  </div></section>;
}
export function WorkspaceRuntime({ tasks, close }: { tasks?: TaskListResponse; close: () => void }) {
  const [page, setPage] = useState(0);
  // Use original task pagination. Only the visible eight projects request status.
  const list = useQuery({ queryKey: ["workspace", "runtime-projects", page], queryFn: () => api.getTasks(8, page * 8), staleTime: 5000, refetchInterval: 10000 });
  const items = list.data?.items ?? (page === 0 ? tasks?.items.slice(0, 8) : []) ?? [];
  return <div className="sp-workspace-runtime"><ResponsiveDrawer title="工作空间运行概况" triggerLabel="查看全局运行概况" open onOpenChange={open => { if (!open) close(); }}><div className="sp-runtime-body">
    <p>集中查看各项目的采集与研究，点击任务返回详情。监控共用串行采集资源；等待原因仅按接口已有信息展示。</p>
    <div className="sp-between"><span>第 {page + 1} 页 · 本页 {items.length} 个项目 · 共 {list.data?.total_count ?? tasks?.total_count ?? "未知"} 个项目</span><button onClick={() => void list.refetch()}>刷新项目列表</button></div>
    {list.isError || list.failureCount > 0 ? <p role="alert">项目列表暂不可刷新，已读项目可能不完整。</p> : null}
    {list.isPending && !items.length ? <p role="status">正在读取项目列表…</p> : null}
    {list.isSuccess && !items.length ? <p>暂无项目。</p> : null}
    {items.map(task => <RuntimeProject key={task.id} task={task} />)}
    <div className="sp-pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页项目</button><button disabled={!list.data?.page?.has_more} onClick={() => setPage(page + 1)}>下一页项目</button></div>
    <details><summary>状态范围与限制</summary><p>每页最多8个项目，采集约5秒、研究约10秒读取一次；项目详情已存在的轮询保持原频率。各接口不是同一原子快照。失联、重试失败或超过15秒未确认时显示未知，不沿用缓存动画。</p><p>监控接口最多最近50条、研究最多最近30次；完整性不足时不声称没有活动任务。项目研究不包含历史对话 Operation、其他服务或其他数据库。暂停字段未记录操作者，不能确认是用户主动暂停。</p><p>计划是否到期仅按带时区字段和本机时钟判断；没有服务端时钟、资源占用方、排队位次或等待原因，不能显示“正在等待另一个项目完成”。有效执行窗口不代表正在采集。</p></details>
  </div></ResponsiveDrawer></div>;
}
