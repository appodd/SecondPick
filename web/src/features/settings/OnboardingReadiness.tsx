import { StatusBadge } from "./SystemPanels";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { request } from "../../api/client";
import type { VisionStatus } from "./VisionSettings";
import type { SetupMode, SystemState } from "./systemState";
import { useState } from "react";
import { readProgress, saveProgress } from "./systemState";
export { collectionPrepared, preparationsReady } from "./systemState";
export function OnboardingReadiness({system,mode='basic',prepareStep}:{system:SystemState;mode?:SetupMode;prepareStep:(step:number)=>void}) {
  const [later,setLater]=useState(()=>readProgress('secondpick-onboarding-vision-later-v1')==='true');
  const vision=useQuery({queryKey:['onboarding-vision'],queryFn:()=>request<VisionStatus>('/api/vision/profiles'),retry:false,refetchOnWindowFocus:false});
  const current=vision.data?.profiles.find(p=>p.id===vision.data?.current_id);
  const label=vision.isError?'状态暂不可确认':vision.isPending?'正在读取':!current?'尚未配置':!current.key_configured||!current.capability_declared?'配置需要完善':current.verification.state==='verified'?(vision.data?.enabled?'已验证并启用':'已验证，当前关闭'):'已保存，尚未验证';
  return <div className="ss-onboarding-extras ss-readiness-stack">
    <section>
      <div className="ss-readiness-content"><div className="ss-readiness-heading"><h3>基础与采集环境</h3><button className="ss-readiness-link" onClick={()=>prepareStep(0)}>前往基础与采集环境 →</button></div>
        <dl className="ss-readiness-checks">{([['应用基础检查',system.states.environment],['采集引擎',system.states.collection]] as const).map(([title,state])=><div key={title}><dt>{title}</dt><dd><StatusBadge state={state}/><small>{state.detail}</small></dd></div>)}</dl>
      </div>
    </section>
    <section><div className="ss-readiness-content"><div className="ss-readiness-heading"><h3>闲鱼连接</h3><button className="ss-readiness-link" onClick={()=>prepareStep(1)}>{system.states.xianyu.tone==='good'?'查看连接':'前往验证'} →</button></div><StatusBadge state={system.states.xianyu}/><small>{system.states.xianyu.detail}</small></div></section>
    <section><div className="ss-readiness-content"><div className="ss-readiness-heading"><h3>{mode==='ai'?'AI 驱动':'AI 研究（可选）'}</h3><button className="ss-readiness-link" onClick={()=>prepareStep(2)}>{mode==='basic'?'切换 AI 增强并配置':system.states.codex.tone==='good'?'查看配置':'前往配置'} →</button></div>{mode==='ai'?<><StatusBadge state={system.states.codex}/><small>{system.states.codex.detail}</small><p>研究授权按项目确认，默认不授权自动研究。完成配置不会创建研究任务。</p></>:<p>基础模式无需 Codex CLI 或研究授权。以后可在设置中配置 AI，再按项目确认研究范围。</p>}</div></section>
    <section><div><h3>视觉模型 <span>可选增强</span></h3><p>{label}{current?` · ${current.provider} / ${current.model}`:''}</p><small>仅用于 AI 图片分析，不影响监控抓取、项目创建及可用的文字研究。保存配置不会自动分析图片。</small>{later&&!current?<p className="ss-vision-later" role="status">已选择稍后配置</p>:null}</div><div className="ss-optional-actions"><Link to="/settings?section=vision">{current?'查看配置':'配置视觉模型'} →</Link>{!current&&!vision.isPending&&!later?<button onClick={()=>{setLater(true);saveProgress('secondpick-onboarding-vision-later-v1','true')}}>跳过，稍后配置</button>:null}</div></section>
  </div>;
}
