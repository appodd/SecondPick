import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { monitorApi, monitorErrors, monitorPhases, type Monitor, type MonitorScope } from "../../api/monitorClient";
import { MonitorConsole } from "./MonitorConsole";
import { StatusBadge, StatusSnapshot, useExecutionStatus } from "../../components/status/ExecutionStatus";
import { monitorExecution } from "../../components/status/statusModel";

const defaults: MonitorScope = { keyword: "", max_pages: 10, max_items: 100, interval_seconds: 1800, max_rounds: 24, collect_seller_profiles: false };
const eventLabels: Record<string, string> = {
  round_started: "开始本轮采集", sync_progress: "已同步采集数据", sync_pending: "仍有数据待同步",
  evidence_retained: "采集记录已保留，注意磁盘空间", round_finished: "本轮运行结束",
};
const countLabels: Record<string, string> = { imported: "商品记录", search_cards: "搜索卡片", price_observations: "报价观察", candidate_pool_count: "去重候选", invalid: "无效记录", duplicates: "重复记录", evidence_bytes: "记录字节数" };
function time(value: string | null) { return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—"; }

// Kept mounted while switching tabs so new evidence also refreshes the conversation context.
export function useMonitors(taskId: number) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["monitors", taskId], queryFn: () => monitorApi.list(taskId),
    enabled: Number.isFinite(taskId), refetchInterval: q => q.state.data?.items.some(m => ["running", "waiting"].includes(m.state)) ? 2000 : 15000 });
  const signature = query.data ? JSON.stringify([query.data.candidate_pool_count, query.data.items.map(m =>
    [m.id, m.state, m.imported, m.result.imported, m.result.search_cards?.imported, m.result.price_observations?.imported])]) : undefined;
  const previous = useRef(signature);
  useEffect(() => {
    if (signature && signature !== previous.current) {
      void client.invalidateQueries({ queryKey: ["task", taskId] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
    }
    previous.current = signature;
  }, [signature, client, taskId]);
  return query;
}

export function useMonitorEvents(monitor: Monitor) {
  const events = useInfiniteQuery({ queryKey: ["monitor-events", monitor.task_id, monitor.id],
    queryFn: ({ pageParam }) => monitorApi.events(monitor.task_id, monitor.id, pageParam),
    initialPageParam: undefined as number | undefined, getNextPageParam: p => p.next_before_id ?? undefined,
    refetchInterval: monitor.state === "running" ? 3000 : false });
  const signature = `${monitor.state}:${monitor.rounds}`;
  const previous = useRef(signature);
  useEffect(() => {
    if (previous.current !== signature) { previous.current = signature; void events.refetch(); }
  }, [signature, events.refetch]);
  return events;
}
export function MonitorDiagnostics({ monitor, compact = false }: { monitor: Monitor; compact?: boolean }) {
  const events = useMonitorEvents(monitor);
  return <div className="monitor-diagnostics">
    {!compact && <p className="muted">仅保留最近 30 天、最多 200 条运行记录；商品证据另行保留。</p>}
    {events.isPending && <p>加载运行记录…</p>}
    {events.error && <p role="alert">{events.error.message}</p>}
    {events.data && !events.data.pages[0].items.length && <p>暂无运行记录。</p>}
    <ol>{events.data?.pages.flatMap(p => p.items).slice(0, compact ? 3 : undefined).map(e => <li key={e.id}>
      <time>{time(e.created_at)}</time> · {eventLabels[e.code] ?? monitorErrors[e.code] ?? monitorPhases[e.code.replace(/^worker_/, "")] ?? "运行状态更新"}
      {Object.entries(e.counts).map(([key, value]) => countLabels[key] ? <span key={key}> · {countLabels[key]} {value}</span> : null)}
    </li>)}</ol>
    {!compact && events.hasNextPage && <button disabled={events.isFetchingNextPage} onClick={() => void events.fetchNextPage()}>加载更早运行记录</button>}
  </div>;
}

function MonitorCard({ monitor: m, enabled, candidatePool }: { monitor: Monitor; enabled: boolean; candidatePool: number }) {
  const client = useQueryClient();
  const [showEvents, setShowEvents] = useState(false);
  const [showConsole, setShowConsole] = useState(false);
  const control = useMutation({ mutationFn: (action: "pause" | "resume" | "stop") => monitorApi.control(m.task_id, m.id, action),
    onSuccess: () => client.invalidateQueries({ queryKey: ["monitors", m.task_id] }) });
  const execution = useExecutionStatus(monitorExecution(m));
  const stopping = !!m.desired_state;
  return <article className="monitor-card" aria-label={`监控 ${m.keyword} #${m.id}`}>
    <div className="monitor-card__heading"><h3>{m.keyword}</h3><StatusBadge status={execution} live /></div>
    {execution.action ? <p>{execution.action}</p> : null}
    <p>每轮最多 {m.max_pages} 页 · 新增详情最多 {m.max_items} 件 · 间隔 {m.interval_seconds / 60} 分钟 · 最多 {m.max_rounds} 轮</p>
    <p className="muted">卖家主页及商品／评价列表：{m.collect_seller_profiles ? "已允许" : "未允许"} · 已尝试 {m.rounds} / {m.max_rounds} 轮 · 剩余 {Math.max(0, m.max_rounds - m.rounds)} 轮</p>
    <p className="muted">尝试次数包含登录失败、采集中止等未完成的轮次，不代表成功采集次数。</p>
    {m.state === "waiting" && <p>下轮计划时间：{time(m.next_run_at)}（采集空闲时执行）</p>}
    <dl className="monitor-totals" aria-label="累计保留的数据">
      <div><dt>本监控累计商品记录</dt><dd>{m.imported}</dd></div>
      <div><dt>当前任务去重候选（含其他来源）</dt><dd>{candidatePool}</dd></div>
    </dl>
    <p className="muted">累计商品记录按已结束的轮次统计，含同一商品的补充版本；运行中的新增在本轮结束后计入。候选按商品去重，暂停、停止或登录失败不会清空已有数据。</p>
    <h4>{m.state === "running" ? "本轮新增入库" : "最近一轮新增入库"}</h4>
    <dl className="monitor-metrics" aria-label="最近一轮同步记录">
      <div><dt>商品记录</dt><dd>{m.result.imported ?? 0}</dd></div>
      <div><dt>搜索卡片</dt><dd>{m.result.search_cards?.imported ?? "—"}</dd></div>
      <div><dt>报价观察</dt><dd>{m.result.price_observations?.imported ?? "—"}</dd></div>
    </dl>
    <p className="muted">以上仅为本轮新增，0 不代表历史数据清零；— 表示本轮未报告该项。三类记录可能指向同一商品，不相加作为候选数量。采集程序返回不代表已覆盖所有商品。</p>
    {m.error_code && <p className="scoped-error">{monitorErrors[m.error_code] ?? monitorErrors.engine_failed}</p>}
    {m.result.sync_pending && <p>还有记录待同步；源记录已保留，候选数量以已入库数据为准。</p>}
    {m.result.retention?.warning && <p>采集记录较多，请留意磁盘空间；系统会保留商品证据。</p>}
    {m.result.diagnostics_available === false && <p>部分运行记录未能保存，已入库商品保留。</p>}
    <p className="muted">暂停或停止后可沿原范围继续，保留已有数据和轮次；已用完轮次时需创建新范围。</p>
    {m.state === "stopped" && m.rounds < m.max_rounds && <p>还剩 {m.max_rounds - m.rounds} 轮；点击继续后按原关键词、权限和频率运行。</p>}
    <div className="monitor-actions">
      {["running", "waiting"].includes(m.state) && <button disabled={stopping || control.isPending} onClick={() => control.mutate("pause")}>暂停监控（含当前采集）</button>}
      {["paused", "needs_attention"].includes(m.state) && <button disabled={!enabled || control.isPending || m.rounds >= m.max_rounds} onClick={() => control.mutate("resume")}>恢复原范围</button>}
      {m.state === "stopped" && m.rounds < m.max_rounds && <button disabled={!enabled || control.isPending} onClick={() => control.mutate("resume")}>继续原监控</button>}
      {m.state !== "stopped" && <button disabled={control.isPending || m.desired_state === "stopped"} onClick={() => control.mutate("stop")}>停止监控（含当前采集）</button>}
      <button aria-expanded={showEvents} onClick={() => setShowEvents(v => !v)}>{showEvents ? "收起运行记录" : "查看运行记录"}</button>
      <button aria-expanded={showConsole} onClick={() => setShowConsole(v => !v)}>{showConsole ? "收起采集日志" : "查看采集日志"}</button>
    </div>
    {m.rounds >= m.max_rounds && <p>已用完确认的轮次；继续采集请创建新范围。</p>}
    {control.error && <p className="scoped-error" role="alert">{control.error.message}</p>}
    {showEvents && <MonitorDiagnostics monitor={m} />}
    {showConsole && <MonitorConsole monitor={m} />}
  </article>;
}

export function MonitorWorkspace({ taskId, query }: { taskId: number; query: ReturnType<typeof useMonitors> }) {
  const client = useQueryClient();
  const [scope, setScope] = useState(defaults);
  const [confirmed, setConfirmed] = useState(false);
  const environment = useQuery({ queryKey: ["monitor-environment"], queryFn: monitorApi.environment });
  const check = useMutation({ mutationFn: monitorApi.checkEnvironment,
    onSuccess: result => client.setQueryData(["monitor-environment"], { result }) });
  const readiness = environment.data?.result;
  const create = useMutation({ mutationFn: () => monitorApi.create(taskId, { ...scope, keyword: scope.keyword.trim() }),
    onSuccess: async () => { setConfirmed(false); await client.invalidateQueries({ queryKey: ["monitors", taskId] }); } });
  const enabled = query.data?.enabled === true && query.data.platform_enabled !== false && !query.isError && readiness?.ready !== false;
  function update(patch: Partial<MonitorScope>) { setScope(s => ({ ...s, ...patch })); setConfirmed(false); create.reset(); }
  return <StatusSnapshot observedAt={query.dataUpdatedAt} staleAfterMs={query.data?.items.some(item => ["waiting", "running"].includes(item.state)) ? 15000 : 45000} unavailable={query.isError || query.failureCount > 0 || query.fetchStatus === "paused"}><section className="workspace-panel monitor-workspace" role="tabpanel" aria-label="监控">
    <h2>持续采集，积累候选</h2>
    <p>确认一次范围后，后台按计划无头采集，无需逐件确认。采集时关闭 AI 分析和通知；有数据后回到对话筛选。</p>
    <div className="monitor-pool" role="status"><strong>{query.data?.candidate_pool_count ?? "—"}</strong><span>当前任务去重候选（含已有数据）</span></div>
    <div className="monitor-actions"><Link to={`?tab=candidates`}>查看全部候选</Link><Link to={`?tab=conversation`}>回到对话筛选</Link><button disabled={query.isFetching} onClick={() => void query.refetch()}>刷新监控状态</button></div>
    {query.isPending && <p>加载监控状态…</p>}
    {query.error && <p role="alert" className="scoped-error">状态更新失败：{query.error.message}。页面可能显示上次数据，请刷新后操作。</p>}
    {query.data && (!query.data.enabled || query.data.platform_enabled === false) && <div className="monitor-notice">
      <p>当前服务未启用监控，可以先填写范围；环境检查通过不会自动启用监控。</p>
      <details><summary>查看启用方法</summary><p>在本项目原网页服务的终端按 Ctrl+C 正常退出，再从项目根目录运行以下命令，随后刷新网页并重新核对范围：</p>
        <code>.\.venv\Scripts\python.exe -m shopping_agent.web.cli --config config/monitor.local.toml</code>
        <p>若已用该配置启动仍无法执行，请检查设置页是否启用了闲鱼平台。</p>
      </details>
    </div>}
    <div className="monitor-environment">
      <button disabled={check.isPending} onClick={() => check.mutate()}>{check.isPending ? "正在检查采集环境…" : "检查采集环境"}</button>
      <p className="muted">检查依赖、采集适配和空白无头浏览器，不访问闲鱼、不读取登录凭据，也不会启动监控。</p>
      {readiness && <><p role="status">{readiness.ready ? "采集环境检查通过，仍需验证登录后使用。" : "采集环境尚未就绪，请处理以下未通过项后重新检查。"}</p>
        <ul>{readiness.checks.map(item => <li key={item.code}>{({ configuration: "引擎配置", revision: "采集器版本", python: "独立运行环境", dependencies: "采集依赖", control_flow: "风控退出适配", browser: "无头浏览器", probe: "环境检查过程" } as Record<string, string>)[item.code] ?? "环境项目"}：{item.ok ? "通过" : "未通过"}</li>)}</ul></>}
      {(check.error || environment.error) && <p role="alert" className="scoped-error">{check.error?.message ?? environment.error?.message}</p>}
    </div>
    <p className="muted">首次使用前请到<Link to="/settings">设置页登录闲鱼并验证</Link>。遇到登录失效或安全验证会停止自动运行；服务重启后先暂停，恢复沿用原确认范围。</p>
    <details className="monitor-create" open={!query.data?.items.length}>
      <summary>创建监控范围</summary>
      <form onSubmit={e => { e.preventDefault(); if (confirmed && enabled && !create.isPending) create.mutate(); }}>
        <fieldset disabled={create.isPending}>
          <legend>本次允许的采集范围</legend>
          <label>监控关键词<input required maxLength={120} value={scope.keyword} onChange={e => update({ keyword: e.target.value })} placeholder="例如：NS2 Pro 手柄" /></label>
          <div className="monitor-fields">
            <label>每轮搜索页数<input type="number" required min={1} max={50} step={1} value={Number.isFinite(scope.max_pages) ? scope.max_pages : ""} onChange={e => update({ max_pages: e.target.valueAsNumber })} /></label>
            <label>每轮新增详情上限<input type="number" required min={1} max={1000} step={1} value={Number.isFinite(scope.max_items) ? scope.max_items : ""} onChange={e => update({ max_items: e.target.valueAsNumber })} /></label>
            <label>轮次间隔（分钟）<input type="number" required min={1} max={1440} step={1} value={Number.isFinite(scope.interval_seconds / 60) ? scope.interval_seconds / 60 : ""} onChange={e => update({ interval_seconds: e.target.valueAsNumber * 60 })} /></label>
            <label>最多运行轮次<input type="number" required min={1} max={1000} step={1} value={Number.isFinite(scope.max_rounds) ? scope.max_rounds : ""} onChange={e => update({ max_rounds: e.target.valueAsNumber })} /></label>
          </div>
          <p className="muted">页数限制搜索范围；详情上限限制新增详情处理量。搜索卡片和报价观察可能多于详情数量，不保证每轮抓满。</p>
          <label className="collection-ack"><input type="checkbox" checked={scope.collect_seller_profiles} onChange={e => update({ collect_seller_profiles: e.target.checked })} />允许访问卖家主页及商品／评价列表（可选，单次资料补充最多等待 30 秒）</label>
          <p>按以上范围运行，轮次间隔从上一轮结束起计算；完成轮次后停止。可随时暂停或停止，已采集数据保留。访问平台可能触发验证或账号限制。</p>
          <label className="collection-ack"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已确认以上范围，允许按此计划定时采集</label>
          <button className="primary-button" disabled={!enabled || !confirmed || !scope.keyword.trim() || create.isPending} type="submit">{create.isPending ? "正在创建…" : "确认范围并启动监控"}</button>
        </fieldset>
        {create.error && <p role="alert" className="scoped-error">{create.error.message}</p>}
        {create.isSuccess && <p role="status">监控已创建，可在下方查看运行状态。</p>}
      </form>
    </details>
    {query.data?.items.map(m => <MonitorCard key={m.id} monitor={m} enabled={enabled} candidatePool={query.data.candidate_pool_count} />)}
    {query.data && !query.data.items.length && <p className="muted">暂无监控，确认范围后开始积累商品。</p>}
  </section></StatusSnapshot>;
}
