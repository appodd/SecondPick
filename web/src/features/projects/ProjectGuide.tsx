import { useEffect, useState } from "react";
import { type MonitorPage } from "../../api/monitorClient";
import type { ProjectOverview } from "../../api/projectClient";
import { readProgress, saveProgress } from "../settings/systemState";
import { overviewJourney } from "./overviewJourney";
import { overviewReport } from "./overviewReport";
import { views, pageDescriptions } from "./projectUi";

/** Presentation only: suggestions navigate to existing confirmation flows. */
export function projectGuide(data: ProjectOverview, monitors?: MonitorPage, needsGoal = false) {
  const journey = overviewJourney(data);
  if (["running","queued","paused","completed","attention"].includes(journey.kind)) return journey;
  if (needsGoal) return {kind:"goal",step:0,title:"先确认选购目标",description:"核对预算和必须满足的条件，再选择如何收集与研究商品。",action:"查看当前选购目标",view:"overview"};
  if (data.report) {
    const candidates=overviewReport(data).candidates.length;
    return {...journey,title:"第一份报告之后，先核对再比较",description:candidates ? `已有研究报告与 ${candidates} 件报告候选。先查看结论的范围、商品证据和待核实问题，再比较候选；报告推荐不是已核验事实。` : "已有研究报告。先查看结论、适用范围与证据；当前没有可展示的报告候选，不代表已经完成选购。",action:candidates?"查看候选与比较":"查看研究依据",view:candidates?"shortlist":"research"};
  }
  if (data.eligible >= data.policy.minimum) return {kind:"sample_ready",step:2,title:"样本已达到设定数量",description:`已有 ${data.eligible} 件初步可比较样本，目标为 ${data.policy.minimum} 件。进入 Agent 研究核对范围和当前执行条件，再确认首轮研究；不会自动提交。`,action:"确认首轮研究范围",view:"research"};
  if (!monitors) return {kind:"monitor_unknown",step:1,title:"确认商品收集进度",description:"监控状态暂未确认。已有商品仍可浏览，请在监控任务中核对采集状态。",action:"查看监控状态",view:"monitors"};
  if (!monitors.items.length) return data.total ? {kind:"sample_pending",step:1,title:"已有商品，先浏览并积累样本",description:`已保存 ${data.total} 件商品，其中 ${data.eligible} 件初步可比较，首轮样本目标为 ${data.policy.minimum} 件。可以先浏览商品，再按需设置监控补充样本。`,action:"浏览已收集商品",view:"products"} : {kind:"no_monitor",step:1,title:"目标已保存，下一步设置监控",description:"确定搜索词和采集范围，预览后确认创建或启动监控。创建选购项目本身不会开始采集。",action:"新建监控",view:"monitors"};
  if (monitors.items.some(m=>m.state==='needs_attention')) return {kind:"monitor_attention",step:1,title:"先处理采集中的问题",description:"有监控需要处理。查看任务中的原因和建议，已有商品与研究结果会保留；不会自动重启。",action:"查看监控异常",view:"monitors"};
  if (monitors.items.some(m=>!m.desired_state&&(m.state==='running'||m.state==='waiting'))) return {kind:"collecting",step:1,title:"监控已安排，正在积累样本",description:`已收集 ${data.total} 件商品，其中 ${data.eligible} 件初步可比较，研究目标为 ${data.policy.minimum} 件。${data.total?'可以先浏览、筛选或收藏商品；初筛符合仍需核实。':'可在监控任务中查看实际执行进度。'}`,action:data.total?"浏览已收集商品":"查看监控进度",view:data.total?"products":"monitors"};
  if(monitors.items.some(m=>m.desired_state&&(m.state==='running'||m.state==='waiting')))return {kind:"monitor_stopping",step:1,title:"监控正在响应暂停或停止请求",description:"已有商品保留，实际停止状态以监控任务的最新记录为准。",action:"查看监控状态",view:"monitors"};
  return {kind:"monitor_idle",step:1,title:"监控尚未继续采集",description:"现有监控已暂停或停止。可以查看原因并按原流程决定是否恢复，也可以继续浏览已保存的商品。",action:"查看监控计划",view:"monitors"};
}

export function ProjectGuide({data,go}:{data:ProjectOverview;go:(view:string)=>void}) {
  const key=`secondpick:project-guide:${data.project.id}`;
  const initialOpen=()=>readProgress(key)==='open'||!data.total&&!data.report&&readProgress(key)!=='dismissed';
  const [preference,setPreference]=useState<{project:number;open:boolean}>(()=>({project:data.project.id,open:initialOpen()}));
  const open=preference.project===data.project.id ? preference.open : initialOpen();
  useEffect(()=>{if(open&&readProgress(key)===null)saveProgress(key,'open')},[open,key]);
  function toggle(value:boolean){setPreference({project:data.project.id,open:value});saveProgress(key,value?'open':'dismissed')}
  if(!open)return <div className="sp-guide-entry"><button onClick={()=>toggle(true)} aria-expanded={false}>项目使用指南</button></div>;
  return <aside className="sp-project-guide sp-project-journey" aria-label="项目使用指南">
    <div className="sp-between"><strong>五个页面分别做什么？</strong><button onClick={()=>toggle(false)}>关闭指南</button></div>
    <section className="sp-guide-pages"><nav aria-label="了解项目页面">{views.map(([view,title,Icon])=><button key={view} onClick={()=>go(view)}><Icon size={15}/><span><b>{title}</b><small>{pageDescriptions[view]}</small></span></button>)}</nav></section>
  </aside>;
}
