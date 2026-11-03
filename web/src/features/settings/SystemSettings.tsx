import { Link, useSearchParams, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { SettingsServices, visionSummaryKey } from "./SettingsServices";
import { useEffect } from "react";
import { Activity, ArrowLeft, Layers, RefreshCw, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { CodexPanel, DiagnosticsPanel, StatusBadge, SystemErrors, XianyuPanel } from "./SystemPanels";
import { useSystemState, collectionPrepared, preparationsReady, setupMode } from "./systemState";
import "../projects/projects.css";
import "./system-settings.css";
import { workspaceReturn } from "../projects/contextNavigation";
import { rememberedWorkspace } from "../projects/workspaceLocation";

import { onboardingHref } from "./onboardingNavigation";
import { VisionSettings } from "./VisionSettings";

const tabs = [["overview", "设置概览", Layers], ["diagnostics", "基础与采集环境", Activity], ["xianyu", "闲鱼账户", ShieldCheck], ["codex", "AI 研究驱动", Zap], ["vision", "视觉模型", Sparkles]] as const;
export function SystemSettings() {
  useEffect(() => { const previous = document.title; document.title = "SecondPick · 系统设置"; return () => { document.title = previous; }; }, []);
  const system = useSystemState();
  const queryClient = useQueryClient();
  const location = useLocation();
  const source = `${location.pathname}${location.search}`;
  const [params, setParams] = useSearchParams();
  const back = workspaceReturn(params.get("returnTo") || rememberedWorkspace());
  function section(key: string) { const next = new URLSearchParams(params); next.set("section", key); setParams(next); }
  const tab = tabs.some(([key]) => key === params.get("section")) ? params.get("section")! : "overview";
  const observedAt = Math.max(system.setup.dataUpdatedAt, system.browser.dataUpdatedAt);
  return <><div className="sp-breadcrumb">SecondPick / 系统设置</div>
      <Link className="sp-status-link ss-return" to={back.href}><ArrowLeft size={15} /> {back.label}</Link>
      <div className="sp-heading"><div><h1>系统设置</h1><p>管理这台设备上的运行环境与服务连接</p></div><div className="sp-actions"><button disabled={system.action.isPending} onClick={()=>{system.action.mutate("refresh");void queryClient.invalidateQueries({queryKey:visionSummaryKey});}}><RefreshCw size={14}/>{system.action.isPending&&system.action.variables==="refresh"?"正在刷新…":"刷新状态"}</button>{system.settings.data?.setup_completed !== false ? <Link className="ss-button ss-guide-button" to={onboardingHref("review", source)}><Sparkles size={15} />使用引导</Link> : null}</div></div>
      <div className="ss-topline"><StatusBadge state={system.healthState} /><span>{observedAt ? `状态读取于 ${new Date(observedAt).toLocaleTimeString()}` : "状态尚未读取"} · 不自动验证平台登录</span></div>
      <div className="ss-layout"><nav className="ss-nav" aria-label="系统配置"><p>系统配置</p>{tabs.map(([key, label, Icon]) => <button key={key} className={tab === key ? "active" : ""} aria-current={tab === key ? "page" : undefined} onClick={() => section(key)}><Icon size={17} />{label}</button>)}<div className="ss-nav-note">系统连接在此管理。项目偏好和长期监控规则请在各自项目中确认。</div></nav>
      <div className="ss-stack"><SystemErrors system={system} />
        {tab === "overview" ? <>{system.settings.data?.setup_completed === false ? <section className="ss-welcome"><div><span className="sp-eyebrow">首次配置尚未完成</span><h2>准备你的选购工作台</h2><p>先检查基础环境与闲鱼连接。基础模式即可监控采集，AI 增强与视觉模型按需配置。</p></div><Link className="ss-button primary" to={onboardingHref("resume", source)}>继续首次配置 →</Link></section> : null}
          {!preparationsReady(system) ? <div className="ss-notice"><strong>部分核心能力尚未确认就绪</strong>{!collectionPrepared(system)?<p>监控抓取需要应用基础检查、闲鱼连接与采集引擎分别就绪。请检查各项状态；已有数据仍可浏览。</p>:null}{setupMode(system.settings.data?.setup_mode)==='ai'&&system.states.codex.tone!=='good'?<p>AI 增强模式还需要可用的 AI 研究驱动与账号授权；采集就绪时可切换基础模式完成引导。</p>:null}</div> : null}
          {system.settings.data?.setup_completed ? <p className="sp-muted">已完成{setupMode(system.settings.data.setup_mode)==='ai'?' AI 增强':'基础'}配置。模式记录不代表正在采集或研究，研究授权仍按项目确认。</p> : null}
          <SettingsServices system={system} onManage={section}/>
          <div className="ss-notice neutral"><strong>已有数据与研究</strong><p>连接失效时仍可查看已保存商品和报告。向导完成记录仅表示已走过配置流程，不表示所有服务健康。</p><Link to="/">查看选购项目 →</Link></div></> : null}
        {tab === "xianyu" ? <XianyuPanel system={system} /> : null}
        {tab === "codex" ? <CodexPanel system={system} /> : null}
        {tab === "vision" ? <VisionSettings /> : null}
        {tab === "diagnostics" ? <DiagnosticsPanel system={system} /> : null}
      </div></div>
  </>;
}
