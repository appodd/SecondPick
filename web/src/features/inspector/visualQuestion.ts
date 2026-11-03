import type { AgentScope } from "../projects/agentContext";
import type { VisualObservation } from "./visualPresentation";
export function visualQuestionScope(o:VisualObservation):AgentScope {
  return {role:"products",ids:[o.listing_id],label:`图片观察追问草稿 · 商品 #${o.listing_id} · 来源研究 #${o.study_id}`,
    question:`请针对观察 ${o.id} 梳理进一步核实方法。AI 曾描述：“${o.visible_content.slice(0,400)}”。限制：“${o.uncertainty.slice(0,300)}”。该说法未经独立核验，当前新鲜度为 ${o.freshness??"unknown"}。本次文字追问未附图片，不得声称看过图；不执行视觉分析、采集或自动调查。`};
}
