import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  createBrowserRouter,
  Navigate,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";

import { api } from "../api/client";
import { queries } from "../api/queries";
import type {
  CandidatePage,
  ListingEvidence,
  MarketOverview as MarketOverviewData,
  TaskDetail,
  TaskListResponse,
} from "../api/types";
import { AppShell } from "../components/layout/AppShell";
import { ContextPanel } from "../components/layout/ContextPanel";
import { CandidateTable } from "../features/candidates/CandidateTable";
import { ComparisonView } from "../features/comparison/ComparisonView";
import { ConversationView } from "../features/conversation/ConversationView";
import { ConversationTimeline } from "../features/conversation/ConversationTimeline";
import { DebugWorkspace } from "../features/debug/DebugWorkspace";
import { ListingEvidencePanel } from "../features/inspector/ListingEvidencePanel";
import { TaskOverview } from "../features/inspector/TaskOverview";
import { MarketOverview } from "../features/market/MarketOverview";
import { MonitorWorkspace, useMonitors } from "../features/monitor/MonitorWorkspace";
import { ResearchTabs, type ResearchTab } from "../features/research/ResearchTabs";
import { SystemSettings } from "../features/settings/SystemSettings";
import { FirstRunEntry, Onboarding } from "../features/settings/Onboarding";
import { TaskHeader } from "../features/tasks/TaskHeader";
import { TaskList } from "../features/tasks/TaskList";
import { ProjectWorkspace } from "../features/projects/ProjectWorkspace";
import { projectReturn } from "../features/projects/contextNavigation";
import { ContextReturnLink } from "../features/projects/ContextReturnLink";

const validTabs = new Set<ResearchTab>([
  "conversation",
  "candidates",
  "comparison",
  "market",
  "monitor",
]);
const validViews = new Set(["research", "debug"]);
const validContextStates = new Set(["open", "closed"]);

function parseTab(value: string | null): ResearchTab {
  return value && validTabs.has(value as ResearchTab)
    ? (value as ResearchTab)
    : "conversation";
}

function parseListing(value: string | null) {
  if (!value || !/^[1-9]\d*$/.test(value)) {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : undefined;
}

function normalizeTaskSearch(searchParams: URLSearchParams, projectId: number) {
  const normalized = new URLSearchParams();
  const tab = searchParams.get("tab");
  const listing = parseListing(searchParams.get("listing"));
  const view = searchParams.get("view");
  const context = searchParams.get("context");

  if (tab && validTabs.has(tab as ResearchTab)) {
    normalized.set("tab", tab);
  }
  if (listing !== undefined) {
    normalized.set("listing", String(listing));
  }
  if (view && validViews.has(view)) {
    normalized.set("view", view);
  }
  if (view !== "debug" && context && validContextStates.has(context)) {
    normalized.set("context", context);
  }
  if (searchParams.has("returnTo")) normalized.set("returnTo", projectReturn(projectId, searchParams.get("returnTo"), 0, true).href);

  return normalized;
}

function WorkbenchLayout({
  children,
  context,
  contextOpen,
  onContextOpenChange,
  contextKey,
}: {
  children: ReactNode;
  context?: ReactNode;
  contextOpen?: boolean;
  onContextOpenChange?: (open: boolean) => void;
  contextKey?: string;
}) {
  const location = useLocation();
  const tasks = useInfiniteQuery(queries.taskPages());
  const taskList = useMemo(
    () => mergeTaskPages(tasks.data?.pages),
    [tasks.data?.pages],
  );

  return (
    <>
      <AppShell
        sidebar={
          <TaskList
            tasks={taskList?.items ?? []}
            isLoading={tasks.isLoading}
            isLoadingMore={tasks.isFetchingNextPage}
            error={tasks.error}
            totalCount={taskList?.total_count ?? 0}
            returnedCount={taskList?.returned_count ?? 0}
            truncated={taskList?.truncated ?? false}
            onLoadMore={tasks.hasNextPage
              ? async () => {
                  await tasks.fetchNextPage();
                }
              : undefined}
          />
        }
        main={children}
        contextOpen={contextOpen}
        contextKey={contextKey}
        navigationKey={`${location.pathname}${location.search}`}
        onContextOpenChange={onContextOpenChange}
        context={context ?? (
          <ContextPanel
            title="任务概览"
            status={tasks.isError ? "任务列表加载失败" : "本地研究"}
            description="选择研究任务后，这里将显示目标、覆盖范围与证据状态。"
          />
        )}
      />
      <FirstRunEntry />
    </>
  );
}

function HomeRoute() {
  return (
    <WorkbenchLayout>
      <WorkspacePlaceholder
        eyebrow="本地只读工作台"
        title="选择一个研究任务"
        description="现有研究记录会显示在这里。点击“新研究”，从一句需求开始。"
      />
    </WorkbenchLayout>
  );
}

function TaskRoute() {
  const { taskId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const numericTaskId = Number(taskId);
  const selectedTab = parseTab(searchParams.get("tab"));
  const settings = useQuery(queries.settings());
  const explicitView = searchParams.get("view");
  const selectedView = explicitView && validViews.has(explicitView)
    ? explicitView as "research" | "debug"
    : settings.data?.preferred_view ?? "research";
  const selectedListingId = parseListing(searchParams.get("listing"));
  const [selectionError, setSelectionError] = useState<{
    taskId: number;
    message: string;
  } | null>(null);
  const task = useQuery(queries.task(numericTaskId));
  const monitors = useMonitors(numericTaskId);
  const candidates = useInfiniteQuery(
    queries.candidatePages(numericTaskId, 50, selectedView === "research"),
  );
  const market = useQuery(queries.market(numericTaskId, selectedView === "research"));
  const debug = useQuery(queries.debug(numericTaskId, selectedView === "debug"));
  const listingEvidence = useQuery(
    queries.listingEvidence(
      numericTaskId,
      selectedListingId,
      selectedView === "research",
    ),
  );
  const candidatePage = useMemo(
    () => mergeCandidatePages(candidates.data?.pages),
    [candidates.data?.pages],
  );
  const marketData = isMarketOverviewData(market.data) ? market.data : undefined;
  const evidenceData = isListingEvidenceData(listingEvidence.data)
    ? listingEvidence.data
    : undefined;

  useEffect(() => {
    const normalized = normalizeTaskSearch(searchParams, numericTaskId);
    if (normalized.toString() !== searchParams.toString()) {
      setSearchParams(normalized, { replace: true });
    }
  }, [searchParams, setSearchParams, numericTaskId]);

  useEffect(() => {
    if (!listingEvidence.isError || selectedListingId === undefined) {
      return;
    }
    setSelectionError({
      taskId: numericTaskId,
      message: listingEvidence.error.message,
    });
    const next = new URLSearchParams(searchParams);
    next.delete("listing");
    setSearchParams(next, { replace: true });
  }, [
    listingEvidence.error,
    listingEvidence.isError,
    numericTaskId,
    searchParams,
    selectedListingId,
    setSearchParams,
  ]);

  function updateSearch(mutator: (next: URLSearchParams) => void) {
    const next = new URLSearchParams(searchParams);
    mutator(next);
    setSearchParams(next);
  }

  function handleSelectTab(tab: ResearchTab) {
    updateSearch((next) => {
      next.set("tab", tab);
    });
  }

  function handleSelectView(view: "research" | "debug") {
    updateSearch((next) => {
      next.set("view", view);
      if (view === "debug") {
        next.delete("context");
      }
    });
  }

  function handleSelectListing(listingId: number) {
    setSelectionError(null);
    updateSearch((next) => {
      next.set("listing", String(listingId));
      next.set("context", "open");
    });
  }

  if (!Number.isFinite(numericTaskId)) {
    return <Navigate to="/" replace />;
  }

  if (task.isError) {
    return (
      <WorkbenchLayout>
        <WorkspacePlaceholder
          eyebrow={`研究任务 ${taskId ?? ""}`}
          title="任务加载失败"
          description={task.error.message}
        />
      </WorkbenchLayout>
    );
  }

  const researchContext = (
    <ContextPanel>
      {selectedListingId === undefined ? (
        <TaskOverview
          candidatePage={candidatePage}
          market={marketData}
          taskDetail={task.data}
        />
      ) : listingEvidence.isLoading ? (
        <p className="muted">加载商品证据...</p>
      ) : evidenceData ? (
        <ListingEvidencePanel evidence={evidenceData} task={task.data} taskId={numericTaskId} onClose={() => updateSearch(next => {
          next.delete("listing");
          next.delete("context");
        })} />
      ) : (
        <p className="scoped-error" role="status">
          {listingEvidence.error?.message ?? "商品证据数据不完整。"}
        </p>
      )}
    </ContextPanel>
  );

  const context = selectedView === "debug" ? (
    <ContextPanel
      title="调试范围"
      status="只读诊断"
      description="仅显示任务覆盖、运行计数和全局平台访问事件。"
    />
  ) : researchContext;

  return (
    <WorkbenchLayout
      context={context}
      contextKey={`${numericTaskId}:${selectedView}:${selectedListingId ?? "overview"}`}
      contextOpen={
        selectedView === "research"
          ? searchParams.get("context") === "open"
          : undefined
      }
      onContextOpenChange={
        selectedView === "research"
          ? (open) => {
              updateSearch((next) => {
                if (open) {
                  next.set("context", "open");
                } else {
                  next.delete("context");
                }
              });
            }
          : undefined
      }
    >
      <section
        className="task-workspace"
        aria-labelledby={selectedView === "debug" ? "debug-title" : "workspace-title"}
      >
        <ContextReturnLink project={numericTaskId} />
        {selectedView === "research" ? (
          <TaskHeader key={numericTaskId} taskDetail={task.data} candidatePage={candidatePage} />
        ) : null}
        <ViewModeSwitch selectedView={selectedView} onSelectView={handleSelectView} />
        {selectedView === "debug" ? (
          debug.isError ? (
            <p className="scoped-error" role="status">{debug.error.message}</p>
          ) : debug.isLoading || !debug.data ? (
            <div className="workspace-panel">加载调试信息...</div>
          ) : (
            <DebugWorkspace snapshot={debug.data} />
          )
        ) : (
          <>
            <ResearchTabs selectedTab={selectedTab} onSelectTab={handleSelectTab} />
            {selectionError?.taskId === numericTaskId ? (
              <p className="scoped-error" role="status">
                {selectionError.message}
              </p>
            ) : null}
            {selectedTab === "monitor" ? <MonitorWorkspace key={numericTaskId} taskId={numericTaskId} query={monitors} /> : <TaskWorkspacePanel
              candidateError={candidates.error}
              candidateIsLoading={candidates.isLoading}
              candidateIsFetchingMore={candidates.isFetchingNextPage}
              candidateHasMore={candidates.hasNextPage}
              candidatePage={candidatePage}
              marketData={marketData}
              marketError={
                market.error ??
                (market.data && !marketData ? new Error("市场概览数据不完整。") : null)
              }
              marketIsLoading={market.isLoading}
              selectedListingId={selectedListingId}
              selectedTab={selectedTab}
              taskId={numericTaskId}
              taskDetail={task.data}
              taskIsLoading={task.isLoading}
              onLoadMore={() => candidates.fetchNextPage()}
              onSelectListing={handleSelectListing}
            />}
          </>
        )}
      </section>
    </WorkbenchLayout>
  );
}

function TaskWorkspacePanel({
  candidateError,
  candidateHasMore,
  candidateIsFetchingMore,
  candidateIsLoading,
  candidatePage,
  marketData,
  marketError,
  marketIsLoading,
  selectedListingId,
  selectedTab,
  taskId,
  taskDetail,
  taskIsLoading,
  onLoadMore,
  onSelectListing,
}: {
  candidateError: Error | null;
  candidateHasMore: boolean;
  candidateIsFetchingMore: boolean;
  candidateIsLoading: boolean;
  candidatePage?: CandidatePage;
  marketData?: MarketOverviewData;
  marketError: Error | null;
  marketIsLoading: boolean;
  selectedListingId?: number;
  selectedTab: ResearchTab;
  taskId: number;
  taskDetail?: TaskDetail;
  taskIsLoading: boolean;
  onLoadMore: () => void;
  onSelectListing: (listingId: number) => void;
}) {
  if (taskIsLoading) {
    return <div className="workspace-panel">加载任务...</div>;
  }

  if (selectedTab === "candidates") {
    return (
      <div className="workspace-panel" role="tabpanel">
        <h2>全部候选</h2>
        {candidateError ? (
          <p className="scoped-error" role="status">{candidateError.message}</p>
        ) : candidateIsLoading || !candidatePage ? (
          <p className="muted">加载候选...</p>
        ) : (
          <CandidateTable
            candidatePage={candidatePage}
            isLoadingMore={candidateIsFetchingMore}
            onLoadMore={candidateHasMore ? () => onLoadMore() : undefined}
            onSelectListing={onSelectListing}
            selectedListingId={selectedListingId}
            taskId={taskId}
          />
        )}
      </div>
    );
  }

  if (selectedTab === "comparison") {
    return (
      <div className="workspace-panel" role="tabpanel">
        <h2>对比</h2>
        <ComparisonView
          taskId={taskId}
          marketMedian={marketData?.overall.price_summary.median}
        />
      </div>
    );
  }

  if (selectedTab === "market") {
    return (
      <div className="workspace-panel" role="tabpanel">
        <h2>市场</h2>
        {marketError ? (
          <p className="scoped-error" role="status">{marketError.message}</p>
        ) : marketIsLoading || !marketData ? (
          <p className="muted">加载市场概览...</p>
        ) : (
          <MarketOverview market={marketData} />
        )}
      </div>
    );
  }

  return (
    <div className="workspace-panel" role="tabpanel">
      <ConversationView
        candidateError={candidateError}
        candidateIsLoading={candidateIsLoading}
        taskDetail={taskDetail}
        candidatePage={candidatePage}
        selectedListingId={selectedListingId}
        onSelectListing={onSelectListing}
      />
    </div>
  );
}

function ViewModeSwitch({
  selectedView,
  onSelectView,
}: {
  selectedView: "research" | "debug";
  onSelectView: (view: "research" | "debug") => void;
}) {
  return (
    <div className="view-mode-switch" role="group" aria-label="工作区视图">
      <button type="button" aria-pressed={selectedView === "research"} onClick={() => onSelectView("research")}>研究视图</button>
      <button type="button" aria-pressed={selectedView === "debug"} onClick={() => onSelectView("debug")}>调试视图</button>
    </div>
  );
}

function WorkspacePlaceholder({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <section className="workspace-placeholder" aria-labelledby="workspace-title">
      <p className="workspace-eyebrow">{eyebrow}</p>
      <h1 id="workspace-title">{title}</h1>
      <p>{description}</p>
    </section>
  );
}

export function createAppRouter() {
  return createBrowserRouter([
    { path: "/", element: <ProjectWorkspace />, children: [
      { index: true, element: <></> },
      { path: "projects/:projectId", element: <></> },
      { path: "settings", element: <SystemSettings /> },
    ] },
    { path: "/legacy", element: <HomeRoute /> },
    { path: "/new", element: <WorkbenchLayout><div className="workspace-panel new-conversation"><ConversationTimeline /></div></WorkbenchLayout> },
    { path: "/tasks/:taskId", element: <TaskRoute /> },
    { path: "/onboarding", element: <Onboarding /> },
    { path: "*", element: <Navigate to="/" replace /> },
  ]);
}

function mergeCandidatePages(pages: CandidatePage[] | undefined) {
  if (!pages || pages.length === 0) {
    return undefined;
  }
  const first = pages[0];
  const last = pages[pages.length - 1];
  return {
    ...first,
    returned_count: pages.reduce((total, page) => total + page.returned_count, 0),
    page: last.page,
    candidates: pages.flatMap((page) => page.candidates),
  } satisfies CandidatePage;
}

function mergeTaskPages(pages: TaskListResponse[] | undefined) {
  if (!pages || pages.length === 0) {
    return undefined;
  }
  const first = pages[0];
  const last = pages[pages.length - 1];
  return {
    ...first,
    items: pages.flatMap((page) => page.items),
    returned_count: pages.reduce(
      (total, page) => total + page.returned_count,
      0,
    ),
    truncated: last.page.has_more,
    page: last.page,
  } satisfies TaskListResponse;
}

function isListingEvidenceData(
  value: ListingEvidence | undefined,
): value is ListingEvidence {
  return Boolean(
    value && value.detail_status && value.seller_fields && value.collection_state,
  );
}

function isMarketOverviewData(
  value: MarketOverviewData | undefined,
): value is MarketOverviewData {
  const candidate = value as
    | { overall?: { price_summary?: unknown }; price_evidence_level?: unknown }
    | undefined;
  return Boolean(candidate?.overall?.price_summary && candidate.price_evidence_level);
}
