import { useEffect, useState } from "react";
import {
  Link,
  Outlet,
  useNavigate,
  useLocation,
  useMatch,
  useSearchParams,
} from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, Layers, Plus, Settings, PanelsTopLeft } from "lucide-react";
import { api } from "../../api/client";
import { projectApi } from "../../api/projectClient";
import { ListingEvidencePanel } from "../inspector/ListingEvidencePanel";
import { ResponsiveDrawer } from "../../components/layout/ResponsiveDrawer";
import { SellerResearch } from "./SellerResearch";
import { Investigations } from "./Investigations";
import { EvidenceChanges } from "./EvidenceChanges";
import { Panel, views, pageDescriptions } from "./projectUi";
import { Overview } from "./Overview";
import { Products } from "./Products";
import { Shortlist } from "./Shortlist";
import { Research } from "./Research";
import { Monitors } from "./Monitors";
import { AgentButton, ProjectAgentProvider, SharedAgentPanel } from "./ProjectAgent";
import { ProjectCreator } from "./ProjectCreator";
import { MonitorCreator } from "./MonitorCreator";
import "./projects.css";
import "./workspace-polish.css";
import { FirstRunEntry } from "../settings/Onboarding";
import { StatusSnapshot } from "../../components/status/ExecutionStatus";
import { ProjectRuntimeNavigation, WorkspaceRuntime } from "./WorkspaceRuntime";
import { contextHref, entryHref, useEntryHref, useViewScrollRestoration, workspaceReturn } from "./contextNavigation";
import { rememberWorkspace, rememberedWorkspace } from "./workspaceLocation";
import { GoalAdjustment, GoalContinuityProvider } from "./GoalContinuity";
import { defaultAgentScope } from "./agentContext";
import { ContextReturnLink } from "./ContextReturnLink";
import { marketHref } from "../market/marketAnalysis";

export function ProjectWorkspace() {
  const projectId = useMatch("/projects/:projectId")?.params.projectId;
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const isSettings = location.pathname === "/settings";
  const back = workspaceReturn(params.get("returnTo") || rememberedWorkspace());
  const id = Number(projectId ?? (isSettings ? back.href.match(/^\/projects\/(\d+)/)?.[1] : undefined));
  const view = views.some(([key]) => key === params.get("view"))
    ? params.get("view")!
    : "overview";
  const navigate = useNavigate();
  const entry = useEntryHref(id);
  useEffect(() => {
    if (projectId) rememberWorkspace(`${location.pathname}${location.search || "?view=overview"}`);
  }, [projectId, location.pathname, location.search]);
  const tasks = useQuery({
    queryKey: ["projects", "list"],
    queryFn: () => api.getTasks(100),
    refetchInterval: 10000,
  });
  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => projectApi.overview(id),
    enabled: Number.isSafeInteger(id) && id > 0,
    refetchInterval: 5000,
  });
  const [newProject, setNewProject] = useState(params.get("create") === "1");
  useEffect(() => {
    if (params.get("create") === "1") {
      setNewProject(true);
      const next = new URLSearchParams(params);
      next.delete("create");
      setParams(next, { replace: true });
    }
  }, [params, setParams]);
  const [monitorDraft, setMonitorDraft] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  useEffect(() => { setMobileMenu(false); }, [location.pathname, view]);
  const [selected, setSelected] = useState<number[]>([]);
  const [listing, setListing] = useState<number>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();
  const evidence = useQuery({
    queryKey: ["project", id, "evidence", listing],
    queryFn: () => api.getListingEvidence(id, listing!),
    enabled: listing !== undefined,
  });
  useEffect(() => {
    setSelected([]);
    setListing(undefined);
    setError("");
    setMonitorDraft(false);
  }, [id]);
  function changeView(next: string) {
    if (isSettings) {
      const source = new URL(back.href, "https://secondpick.local");
      navigate(source.searchParams.get("view") === next ? back.href : `/projects/${id}?view=${next}`);
    } else setParams({ view: next });
  }
  async function action(fn: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
      await queryClient.invalidateQueries({ queryKey: ["project", id] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const data = project.data;
  useViewScrollRestoration(!!data || isSettings);
  return (
    <StatusSnapshot observedAt={project.dataUpdatedAt} unavailable={project.isError || project.failureCount > 0 || project.fetchStatus === "paused"}><ProjectAgentProvider key={id > 0 ? String(id) : "home"} data={data} view={view} selected={selected}><GoalContinuityProvider data={data} unavailable={project.isError || project.failureCount > 0 || project.fetchStatus === "paused"}><div className={`sp-shell${isSettings ? " ss-shell" : ""}`}>
      <header className="sp-top">
        <Link className="sp-brand" to="/">
          <span>
            <Sparkles size={21} />
          </span>
          SecondPick <small>AI 二手选购研究</small>
        </Link>
        <button className="sp-mobile-tools" aria-expanded={mobileMenu} aria-controls="sp-workspace-navigation" onClick={() => setMobileMenu(open => !open)}>{mobileMenu ? "收起导航" : "更多导航"}</button>
      </header>
      <aside id="sp-workspace-navigation" className={`sp-side${mobileMenu ? " sp-mobile-expanded" : ""}`}>
        <div className="sp-project-entry">
        <select
          className="sp-mobile-project"
          aria-label="切换选购项目"
          value={id || ""}
          onChange={(event) =>
            navigate(
              event.target.value ? `/projects/${event.target.value}` : "/",
            )
          }
        >
          <option value="">选择选购项目</option>
          {tasks.data?.items.map((task) => (
            <option key={task.id} value={task.id}>
              {task.title}
            </option>
          ))}
        </select>
        <div className="sp-side-label">选购项目</div>
        <button className="sp-new" onClick={() => setNewProject(true)}>
          <Plus size={17} />
          新建选购项目
        </button>
        </div>
        <div className="sp-project-region">
        {tasks.isLoading ? <p>加载项目…</p> : null}
        {tasks.error ? (
          <p role="alert">
            项目加载失败 <button onClick={() => tasks.refetch()}>重试</button>
          </p>
        ) : null}
        <ProjectRuntimeNavigation tasks={tasks.data} active={id} returnHref={isSettings ? back.href : undefined} />
        </div>
        <section className="sp-nav-group" aria-labelledby="workspace-nav-label">
          <div className="sp-side-label" id="workspace-nav-label">全局工作空间</div>
          <nav aria-label="全局工作空间">
            <button className={`sp-runtime-entry${!isSettings && params.get("runtime") === "1" ? " active" : ""}`} aria-current={!isSettings && params.get("runtime") === "1" ? "page" : undefined} onClick={() => {
              if (isSettings) { const target = new URL(back.href, "https://secondpick.local"); target.searchParams.set("runtime", "1"); navigate(`${target.pathname}${target.search}`); }
              else { const next = new URLSearchParams(params); next.set("runtime", "1"); setParams(next); }
            }}><PanelsTopLeft size={17} />运行中心</button>
          </nav>
        </section>
        {id > 0 ? (
          <section className="sp-nav-group" aria-labelledby="project-nav-label">
            <div className="sp-side-label" id="project-nav-label">当前项目</div>
            <nav aria-label="当前项目">
              {[{ title: "决策与商品", items: views.slice(0, 3) }, { title: "采集与研究执行", items: views.slice(3) }].map(group => <div className="sp-project-nav-section" role="group" aria-label={group.title} key={group.title}>
              <div className="sp-nav-subheading" aria-hidden="true">{group.title}</div>
              {group.items.map(([key, name, Icon]) => (
                <button
                  key={key}
                  aria-current={!isSettings && view === key && params.get("runtime") !== "1" ? "page" : undefined}
                  className={!isSettings && view === key && params.get("runtime") !== "1" ? "active" : ""}
                  onClick={() => changeView(key)}
                >
                  <Icon size={17} />
                  {name}
                </button>
              ))}
              </div>)}
            </nav>
          </section>
        ) : null}
        <div className="ss-sidebar-bottom"><FirstRunEntry suppress={newProject || isSettings} /><Link className={`ss-side-link${isSettings ? " active" : ""}`} aria-current={isSettings ? "page" : undefined} to={isSettings ? `${location.pathname}${location.search}` : id > 0 ? entry("/settings") : "/settings"}><Settings size={17} />设置</Link></div>
      </aside>
      <main
        className={`sp-main ${isSettings ? "ss-main" : ""}`}
      >
        {isSettings ? <Outlet /> : null}
        {!projectId && !isSettings ? (
          <>
            <div className="sp-heading">
              <div>
                <p className="sp-eyebrow">你的下一次理性选购</p>
                <h1>{tasks.data?.items.length ? "继续你的选购研究" : "把寻找，交给研究。"}</h1>
                <p>建立选购目标，持续观察市场，用有依据的结论做决定。</p>
              </div>
            </div>
            <Panel>
              <Sparkles className="sp-blue" size={28} />
              <h2>{tasks.data?.items.length ? "选择已有项目，或开始新的选购" : "开始一个选购项目"}</h2>
              <p>
                告诉 SecondPick
                想买什么。确认需求和监控计划后，商品与研究成果会积累在这里。
              </p>
              <button
                className="sp-primary"
                onClick={() => setNewProject(true)}
              >
                新建选购项目
              </button>
            </Panel>
            <div className="sp-home-grid">
              {tasks.data?.items.map((task) => (
                <Link
                  className="sp-panel"
                  to={`/projects/${task.id}`}
                  key={task.id}
                >
                  <Layers size={20} />
                  <h2>{task.title}</h2>
                  <p>
                    {" "}
                    {task.status === "completed" ? "已完成" : "选购研究"}
                  </p>
                </Link>
              ))}
            </div>
          </>
        ) : null}
        {projectId && project.isLoading ? (
          <Panel>
            <p role="status">正在加载真实项目状态…</p>
          </Panel>
        ) : null}
        {projectId && project.error ? (
          <Panel>
            <h2>项目暂不可用</h2>
            <p role="alert">{project.error.message}</p>
            <button onClick={() => project.refetch()}>重新连接</button>
          </Panel>
        ) : null}
        {data && !isSettings ? (
          <>
            <div className="sp-breadcrumb">
              选购项目 / {data.project.title} /{" "}
              {views.find(([key]) => key === view)?.[1]}{data.policy.budget !== null ? ` · 预算 ¥${data.policy.budget.toLocaleString()}` : ""}
            </div>
            <div className="sp-heading">
              <div>
                <h1>
                  {views.find(([key]) => key === view)?.[1]}
                </h1>
                <p className="sp-page-description">{view === "monitors" ? <>管理搜索与采集计划，查看运行状态；采集到的商品可在<Link to={contextHref(id, `/projects/${id}?view=products`, `${location.pathname}${location.search || "?view=monitors"}`)}>「全部商品」</Link>中查看。</> : view === "research" ? <>基于<Link to={contextHref(id, `/projects/${id}?view=products`, `${location.pathname}${location.search || "?view=research"}`)}>「全部商品」</Link>与当前选购目标开展研究，也可针对指定商品或问题深入分析。</> : pageDescriptions[view as keyof typeof pageDescriptions]}</p>
              </div>
              <div className="sp-actions">
                {view === "research" ? <AgentButton className="sp-primary" scope={{ ...defaultAgentScope(data, "research"), question: "深入研究这些商品，请重点关注：" }}><Plus size={15} />新建研究任务</AgentButton> : null}
                {view === "monitors" ? <button
                  className="sp-primary sp-new-monitor-action"
                  onClick={() => setMonitorDraft(true)}
                >
                  <Plus size={15} />
                  新建监控
                </button> : null}
              </div>
            </div>
            {project.isRefetchError ? (
              <p className="sp-error" role="status">
                连接已中断，显示上次成功的数据；正在重试。
              </p>
            ) : null}
            {error ? (
              <p className="sp-error" role="alert">
                {error}
              </p>
            ) : null}
            <ContextReturnLink project={id} />
            {data.region_preference?.legacy_unverified ? <aside className="sp-muted" role="note"><p>历史地区偏好「{data.region_preference.legacy_city}」待确认。{data.report ? "旧报告中的地区相关结论需复核。" : null}</p><details className="sp-copy-help"><summary>地区来源与调整</summary><p>历史城市「{data.region_preference.legacy_city}」的来源待确认，记录已保留，不据此优先推荐同城商品。{data.report ? "旧报告可能受旧版地区排序影响，请核对地区相关结论；需要调整时可确认选购条件或手动研究。" : "可在调整选购条件中明确地区要求。"}</p></details></aside> : null}

            {view === "overview" ? (
              <Overview
                key={`overview-${id}`}
                data={data}
                go={next => navigate(contextHref(id, `/projects/${id}?view=${next}`, `${location.pathname}${location.search || "?view=overview"}`))}
                select={setListing}
                busy={busy}
                action={action}
              />
            ) : null}
            {view === "products" ? (
              <Products
                data={data}
                selected={selected}
                setSelected={setSelected}
                select={setListing}
                action={action}
                busy={busy}
              />
            ) : null}
            {view === "shortlist" ? (
              <Shortlist data={data} select={setListing} action={action} />
            ) : null}
            {view === "monitors" ? (
              <Monitors
                id={id}
                action={action}
                busy={busy}
              />
            ) : null}
            {view === "research" ? (
              <Research data={data} action={action} busy={busy} select={setListing} />
            ) : null}
          </>
        ) : null}
      </main>
      {data && !isSettings ? <GoalAdjustment data={data} hideTrigger /> : null}
      <SharedAgentPanel select={setListing} />
      {newProject ? (
        <ProjectCreator
          close={() => setNewProject(false)}
          created={async (newId, monitor) => {
            setNewProject(false);
            await queryClient.invalidateQueries({
              queryKey: ["projects", "list"],
            });
            navigate(
              `/projects/${newId}${monitor ? "?view=monitors&setup=1" : ""}`,
            );
            setMonitorDraft(monitor);
          }}
        />
      ) : null}
      {data && (monitorDraft || params.get("setup") === "1") ? (
        <MonitorCreator
          id={id}
          initialKeyword={params.get('draftKeyword') ?? undefined}
          goal={params.get("draftGoal") ?? data.project.goal}
          close={() => {
            setMonitorDraft(false);
            const next = new URLSearchParams(params); next.delete("setup"); next.delete("draftGoal"); next.delete('draftKeyword'); setParams(next, { replace: true });
          }}
          saved={async () => {
            setMonitorDraft(false);
            if (view !== "monitors") navigate(entryHref(id, `/projects/${id}?view=monitors`, `${location.pathname}${location.search || "?view=overview"}`));
            else { const next = new URLSearchParams(params); next.delete("setup"); next.delete("draftGoal"); next.delete('draftKeyword'); setParams(next, { replace: true }); }
            await queryClient.invalidateQueries({ queryKey: ["project", id] });
            await queryClient.invalidateQueries({ queryKey: ["goal-monitors", id] });
          }}
        />
      ) : null}
      {params.get("runtime") === "1" ? <WorkspaceRuntime tasks={tasks.data} close={() => { const next = new URLSearchParams(params); next.delete("runtime"); setParams(next, { replace: true }); requestAnimationFrame(() => document.querySelector<HTMLElement>(".sp-runtime-entry")?.focus()); }} /> : null}
      {listing !== undefined ? (
        <ResponsiveDrawer
          title="商品与卖家证据"
          triggerLabel="查看选中商品"
          open
          onOpenChange={(open) => {
            if (!open) setListing(undefined);
          }}
        >
          <div className="sp-detail">
            <Investigations id={id} listing={listing} />
            {data ? <EvidenceChanges data={data} listing={listing} /> : null}
            {evidence.isLoading ? (
              <p>加载证据…</p>
            ) : evidence.error ? (
              <p role="alert">
                {evidence.error.message}
                <button onClick={() => evidence.refetch()}>重试</button>
              </p>
            ) : evidence.data ? (
              <>
                <ListingEvidencePanel taskId={id} project={data} beforeQuestion={() => setListing(undefined)} marketReference={() => { setListing(undefined); navigate(contextHref(id, marketHref(id, listing), `${location.pathname}${location.search || "?view=overview"}`)); }} sellerResearch={<SellerResearch key={listing} id={id} listing={listing} evidence={evidence.data} studies={data?.studies} />} evidence={evidence.data} imageUrls={data?.cards.filter(card => card.listing_id === listing && card.image_url).map(card => card.image_url!) ?? []} />
              </>
            ) : null}
          </div>
        </ResponsiveDrawer>
      ) : null}
    </div></GoalContinuityProvider></ProjectAgentProvider></StatusSnapshot>
  );
}
