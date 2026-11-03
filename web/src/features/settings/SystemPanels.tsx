import { Activity, Database, Info, RefreshCw, ShieldCheck, Zap } from "lucide-react";
import { browserStageLabel, isBrowserActive } from "../../api/browserClient";
import { type ServiceState, type SystemState } from "./systemState";
import { StatusBadge as SharedStatusBadge } from "../../components/status/ExecutionStatus";
import { serviceStatus } from "../../components/status/statusModel";

export function StatusBadge({ state }: { state: ServiceState }) {
  return <SharedStatusBadge status={serviceStatus(state)} className="ss-badge" />;
}
function ObservedServiceBadge({ system, source, state, field = "codex" }: { system: SystemState; source: "setup" | "engine"; state: ServiceState; field?: "environment" | "codex" }) {
  const query = source === "setup" ? system.setup : system.engine;
  return <StatusBadge state={query.isError ? { label: "状态暂不可确认", tone: "unknown", detail: "状态读取失败，上次结果无法确认当前就绪情况。" }
    : system.observe(state, source === "setup" ? system.observedAt[field] : system.observedAt.engine, query.isFetching)} />;
}
export function StateCards({ system, includeEngine=true }: { system: SystemState; includeEngine?:boolean }) {
  const entries:[string,ServiceState][]=[['应用基础检查',system.states.environment],['闲鱼连接',system.states.xianyu],...(includeEngine?[["采集引擎",system.states.collection] as [string,ServiceState]]:[]),['AI 研究驱动',system.states.codex]];
  return <div className="ss-cards">{entries.map(([title, state]) => <section className="ss-card" key={title}><p>{title}</p><StatusBadge state={state} /><p>{state.detail}</p></section>)}</div>;
}
export function SystemErrors({ system }: { system: SystemState }) {
  const errors = [["后端连接", system.health.error], ["环境与驱动", system.setup.error], ["用户设置", system.settings.error],
    ["闲鱼状态", system.browser.error], ["采集环境", system.engine.error]] as const;
  return <>{errors.filter(([, error]) => error).map(([label, error]) => <div className="ss-notice ss-status-error" role="alert" key={label}>
    <strong>{label}暂不可用</strong><p>{error?.message}。这一部分的状态无法确认，其他已读取的数据仍可查看。</p>
    <ActionButton system={system} kind="refresh">重新读取状态</ActionButton></div>)}
    {system.action.error ? <div className="ss-notice ss-status-error" role="alert"><strong>操作未完成</strong><p>{system.action.error.message}</p><p>未确认成功。可修复原因后重试原操作。</p></div> : null}</>;
}
export function ActionButton({ system, kind, children }: { system: SystemState; kind: Parameters<SystemState["action"]["mutate"]>[0]; children: React.ReactNode }) {
  return <button disabled={system.action.isPending} onClick={() => system.action.mutate(kind)}>
    <RefreshCw size={14} />{system.action.isPending && system.action.variables === kind ? "处理中…" : children}</button>;
}
export function EnvironmentPanel({ system }: { system: SystemState }) {
  return <section className="ss-card"><div className="ss-panel-title"><Database /><div><h2>应用基础检查</h2><p>检查应用配置与项目数据库；采集依赖由下方采集引擎单独检查。</p></div><StatusBadge state={system.states.environment} /></div>
    {system.setup.isLoading ? <p role="status">正在读取环境…</p> : null}
    <div className="ss-rows">{!system.setup.isError && system.setup.data?.environment.map(check => <div className="ss-row" key={check.name}><div><b>{({ config: "应用配置", database: "项目数据库" } as Record<string, string>)[check.name] ?? check.name}</b><p>{check.detail}</p>{check.name === "config" && check.detail.includes("default_city=") ? <p>此为兼容旧工具的技术配置，不代表项目交易地区偏好，也不限定监控采集地区。</p> : null}</div><ObservedServiceBadge system={system} source="setup" field="environment" state={{ label: check.ok ? "通过" : "未通过", tone: check.ok ? "good" : "warn", detail: "" }} /></div>)}</div>
    <div className="ss-panel-foot"><ActionButton system={system} kind="environment">检查应用基础环境</ActionButton></div>
  </section>;
}
export function XianyuPanel({ system }: { system: SystemState }) {
  const browser = system.browser.data;
  const job = browser?.login_job;
  const active = isBrowserActive(job);
  return <section className="ss-card"><div className="ss-panel-title"><ShieldCheck /><div><h2>闲鱼账户</h2><p>在本机浏览器中登录，复用现有登录态管理。</p></div><StatusBadge state={system.states.xianyu} /></div>
    <div className="ss-rows"><div className="ss-row"><div><b>登录有效性</b><p>{system.states.xianyu.detail}</p></div><StatusBadge state={system.states.xianyu} /></div>
      <div className="ss-row"><div><b>本地登录资料</b><p>{system.setup.isError || !system.setup.data ? "未知" : system.setup.data.xianyu.profile_present ? "检测到资料目录；内容与有效期未检查。" : "尚未检测到资料。"}</p></div></div>
      <div className="ss-row"><div><b>账户标识与登录时间</b><p>后端未提供安全账户标识或授权有效期。</p></div><span>未提供</span></div></div>
    {job ? <div className="ss-notice neutral" role="status"><strong>登录任务 #{job.id} · {browserStageLabel[job.stage] ?? job.stage}</strong><p>任务状态：{job.state}</p>{job.error_detail ? <p>{job.error_detail}</p> : null}<p>后台浏览器任务的结果会在这里更新。</p></div> : null}
    {browser && !browser.enabled ? <div className="ss-notice"><strong>后端未启用闲鱼登录</strong><p>无法在网页打开登录窗口。请维护者检查现有平台与登录权限配置；此处不会修改采集策略。</p></div> : null}
    {browser?.active_job && !active ? <p>浏览器正被任务 #{browser.active_job.id} 使用，请等待该任务结束。</p> : null}
    <div className="ss-login-reminder" role="note"><Info size={17} aria-hidden="true"/><p><strong>先验证连接，再关闭浏览器。</strong>在弹出的闲鱼网页中完成登录后，请保持浏览器打开，返回这里点击“我已登录，验证连接”；验证通过后再关闭浏览器。</p></div>
    <div className="ss-panel-foot">
      <ActionButton system={system} kind="refresh">刷新已保存状态</ActionButton>
      <button className="sp-primary" disabled={system.action.isPending || system.browser.isError || !browser?.enabled || !!browser.active_job} onClick={() => system.action.mutate("login")}>{system.states.xianyu.tone === "good" ? "重新打开登录窗口" : "打开闲鱼登录窗口"}</button>
      {active && job?.state === "running" && ["waiting_login", "login_not_verified"].includes(job.stage) ? <ActionButton system={system} kind="verify">我已登录，验证连接</ActionButton> : null}
      {active && !job?.stop_requested ? <ActionButton system={system} kind="cancel">取消登录任务</ActionButton> : null}
    </div>
  </section>;
}
export function CodexPanel({ system }: { system: SystemState }) {
  const codex = system.setup.isError ? undefined : system.setup.data?.codex;
  return <section className="ss-card"><div className="ss-panel-title"><Zap /><div><h2>AI 研究驱动</h2><p>沿用后端现有 Codex CLI 驱动。</p></div><StatusBadge state={system.states.codex} /></div>
    <div className="ss-rows"><div className="ss-row"><div><b>基础可用性</b><p>{system.states.codex.detail}</p></div><StatusBadge state={system.states.codex} /></div>
      <div className="ss-row"><div><b>CLI 检测</b><p>后端服务环境是否能找到现有 CLI。</p></div><ObservedServiceBadge system={system} source="setup" state={{ label: !codex ? "未知" : codex.cli_available ? "已找到" : "未找到", tone: !codex ? "unknown" : codex.cli_available ? "good" : "warn", detail: "" }} /></div>
      <div className="ss-row"><div><b>CLI 授权</b><p>由后端现有授权检查返回，不读取或展示凭据。</p></div><ObservedServiceBadge system={system} source="setup" state={{ label: !codex || !codex.cli_available || codex.detail === "check failed" ? "未知" : codex.auth_available ? "授权可用" : "授权未通过", tone: !codex || !codex.cli_available || codex.detail === "check failed" ? "unknown" : codex.auth_available ? "good" : "warn", detail: "" }} /></div>
      <div className="ss-row"><div><b>版本与当前运行状态</b><p>现有检测接口未提供可信的版本和实时任务状态。</p></div><span>未知</span></div>
      <div className="ss-row"><div><b>端到端研究测试</b><p>基础检测仅检查 CLI 是否可找到及授权状态。可在选购项目中提交真实研究并查看结果。</p></div><span>未测试</span></div></div>
    <div className="ss-panel-foot"><ActionButton system={system} kind="codex">检测 CLI 与授权</ActionButton></div>
  </section>;
}
export function DiagnosticsPanel({ system }: { system: SystemState }) {
  return <><EnvironmentPanel system={system}/><EnginePanel system={system}/></>;
}
export function EnginePanel({ system }: { system: SystemState }) {
  const checked = system.engine.data?.result;
  return <section className="ss-card"><div className="ss-panel-title"><Activity /><div><h2>采集引擎</h2><p>检查引擎配置、采集依赖及浏览器，不访问商品或验证闲鱼登录。</p></div><StatusBadge state={system.states.collection} /></div>
    <p>{system.states.collection.detail}</p><p>最近环境检查：{checked?.checked_at ? new Date(checked.checked_at).toLocaleString() : "尚无结果"}</p>
    {checked?.checks.map(check => <div className="ss-row" key={check.code}><b>{({ configuration: "引擎配置", revision: "引擎版本兼容性", python: "Python 环境", dependencies: "采集依赖", control_flow: "采集控制流程", browser: "浏览器启动", probe: "探测进程" } as Record<string, string>)[check.code] ?? check.code}</b><ObservedServiceBadge system={system} source="engine" state={{ label: check.ok ? "通过" : "未通过", tone: system.engine.isError ? "unknown" : check.ok ? "good" : "warn", detail: "" }} /></div>)}
    <div className="ss-panel-foot"><ActionButton system={system} kind="engine">检查采集引擎环境</ActionButton></div>
    <p className="ss-fine">引擎检查通过不代表闲鱼登录有效，也不会启动监控。缺少引擎配置或依赖时，按检查结果在本机补齐后重新检查。</p></section>;
}
