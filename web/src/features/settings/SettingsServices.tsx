import { Activity, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { request } from "../../api/client";
import { StatusBadge } from "./SystemPanels";
import type { ServiceState, SystemState } from "./systemState";
import type { VisionStatus } from "./VisionSettings";

export const visionSummaryKey = ["settings", "vision-summary"];

export function SettingsServices({ system, onManage }: { system: SystemState; onManage: (key: string) => void }) {
  const vision = useQuery({ queryKey: visionSummaryKey, queryFn: () => request<VisionStatus>("/api/vision/profiles"), retry: false });
  const current = vision.data?.profiles.find(p => p.id === vision.data.current_id);
  let visionState: ServiceState = { label: "正在读取", tone: "unknown", detail: "读取视觉模型配置…" };
  if (vision.isError) visionState = { label: "状态暂不可确认", tone: "unknown", detail: "无法读取配置，请刷新状态或进入管理查看。" };
  else if (vision.data) {
    const name = current ? `${current.provider === "deepseek" ? "DeepSeek" : current.provider} / ${current.model}` : "尚未选择当前模型";
    const verification = current?.verification.state;
    visionState = {
      label: vision.data.enabled ? "视觉研究已启用" : "视觉研究已关闭",
      tone: vision.data.enabled ? "good" : "unknown",
      detail: name,
    };
    if (vision.data.enabled && (!current?.key_configured || !current.capability_declared || verification !== "verified")) {
      visionState = { label: "启用状态需核对", tone: "warn", detail: name };
    }
    if (!current) visionState.detail += vision.data.profiles.length ? ` · 已保存 ${vision.data.profiles.length} 份配置` : " · 可稍后配置";
  }
  const connection: ServiceState | undefined = current ? {
    label: ({ verified: "连接已验证", failed: "验证失败", verifying: "正在验证" } as Record<string,string>)[current.verification.state] ?? "尚未验证",
    tone: current.verification.state === "verified" ? "good" : current.verification.state === "failed" ? "warn" : "unknown",
    detail: "",
  } : undefined;

  return <section className="ss-card ss-services" aria-label="连接与运行服务">
    <h2>连接与运行服务</h2><p>查看当前状态，进入对应设置完成配置与检查。</p>
    <div className="ss-row ss-service-row"><Activity size={20}/><div className="ss-service-info"><b>基础与采集环境</b><p>检查应用配置、项目数据库、采集依赖与浏览器。</p></div>
      <div className="ss-service-statuses" aria-label="基础与采集环境状态"><div><span>应用基础</span><StatusBadge state={system.states.environment}/></div><div><span>采集引擎</span><StatusBadge state={system.states.collection}/></div></div>
      <button aria-label="管理基础与采集环境" onClick={()=>onManage("diagnostics")}>管理</button>
    </div>
    <div className="ss-row ss-service-row"><ShieldCheck size={20}/><div className="ss-service-info"><b>闲鱼账户</b><p>{system.states.xianyu.detail}</p></div><div className="ss-service-statuses"><StatusBadge state={system.states.xianyu}/></div><button aria-label="管理闲鱼账户" onClick={()=>onManage("xianyu")}>管理</button></div>
    <div className="ss-row ss-service-row"><Zap size={20}/><div className="ss-service-info"><b>AI 研究驱动</b><p>{system.states.codex.detail}</p></div><div className="ss-service-statuses"><StatusBadge state={system.states.codex}/></div><button aria-label="管理 AI 研究驱动" onClick={()=>onManage("codex")}>管理</button></div>
    <div className="ss-row ss-service-row"><Sparkles size={20}/><div className="ss-service-info"><b>视觉模型 <span className="ss-service-optional">可选增强</span></b><p>{visionState.detail}</p></div><div className="ss-service-statuses"><StatusBadge state={visionState}/>{connection?<StatusBadge state={connection}/>:null}</div><button aria-label="管理视觉模型" onClick={()=>onManage("vision")}>管理</button></div>
  </section>;
}
