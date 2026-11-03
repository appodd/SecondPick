import { productResearchStatus } from "../../components/status/statusModel";
import type { ProjectOverview } from "../../api/projectClient";
import { candidateIds } from "./reportCandidates";
export { candidateIds } from "./reportCandidates";
import { filterInsight, productInsights, matchLabels, aiLabels, type ProductInsights } from "./productInsights";

export type AgentRole = "interpret" | "products" | "decision" | "planning" | "direction";
export interface AgentScope { role: AgentRole; ids: number[]; label: string; question?: string; filters?: string; report?: ProjectOverview["report"]; researchContext?: string; studyId?:number;reportId?:number }
export const agentRoles: Record<AgentRole, string> = { interpret: "研究解读", products: "商品调查", decision: "选购决策", planning: "搜索规划", direction: "研究指挥" };
export const agentQuestions: Record<AgentRole, string> = {
  interpret: "当前结论最重要的依据和局限是什么？还有哪些信息会改变推荐？",
  products: "核对本次商品的配置、价格、机况与卖家描述，区分证据、自述及待确认事项。",
  decision: "结合选购目标，对比这些候选的适用性、配置、挂牌价、机况、卖家与交易条件。说明关键取舍、推荐依据及购买前必须核实的问题，不仅给排名。",
  planning: "", direction: "本次优先关注哪些商品、哪些证据不足？说明已有研究覆盖和下一步可核实事项。",
};
export function defaultAgentScope(data: ProjectOverview, view: string): AgentScope {
  if(view==='overview'&&!data.report){const recent=data.studies.find(s=>s.state==='completed'&&s.result&&s.goal_revision===data.goal_context?.current_revision);if(recent)return {role:'interpret',ids:recent.listing_ids.filter(id=>data.cards.some(c=>c.listing_id===id)),label:`研究 #${recent.id} 的已保存范围；尚无当前综合报告`};}
  if (view === "monitors") return { role: "planning", ids: [], label: "当前项目选购目标；仅准备可编辑草案" };
  if (view === "shortlist") { const ids = [...new Set([...candidateIds(data), ...data.favorites])]; return { role: "decision", ids, label: `AI 推荐与收藏，共 ${ids.length} 件（可在清单勾选缩小范围）` }; }
  if (view === "overview") { const ids = candidateIds(data); return { role: "interpret", ids: ids.length ? ids : data.cards.slice(0, 20).map(card => card.listing_id), report: data.report, label: `当前报告 ${data.report ? `#${data.report.id}` : "尚未生成"}；${ids.length ? "报告候选" : "当前商品前20件以内"}` }; }
  const waiting = data.cards.filter(card => ["waiting", "summarized", "needs_information"].includes(card.research_state));
  return { role: view === "products" ? "products" : "direction", ids: (waiting.length ? waiting : data.cards).slice(0, 20).map(card => card.listing_id), label: `${waiting.length ? "待研究/仅批次概述/待补资料" : "当前项目商品"}前20件以内；临时研究指令`, researchContext: JSON.stringify({ scope: "当前版本覆盖，互斥分类；批次概述、规则排除不计逐项分析。任务只返回最近30次，不据此推断完整队列或完成百分比。", total: data.total, coverage: data.coverage, scheduling: { paused: data.policy.paused, auto_research: data.policy.auto_research }, recent_runs: data.studies.map(run => ({ id: run.id, kind: run.kind, state: run.state, snapshot_at: run.snapshot_at, finished_at: run.finished_at })) }) };
}
export function agentInstruction(scope: AgentScope, question: string) {
  const context = `SecondPick ${agentRoles[scope.role]}。范围：${scope.label}。商品ID：${scope.ids.join("、")}。${scope.filters ? `筛选说明：${scope.filters}。` : ""}\n只针对本次输入，结合选购目标和已有证据分析；区分卖家自述、独立证据、未知和冲突。挂牌价不是成交价，低价不等于可靠。不得更改持久研究策略、监控、收藏，不发起采集或交易。\n${scope.researchContext ? `当前研究管理上下文：${scope.researchContext}\n` : ""}用户本次问题：${question}`;
  const metadata = scope.report ? `\n所追问的报告：#${scope.report.id}；目标版本：${scope.report.goal_revision ?? "未核验"}（可能为历史目标，不代表当前适用）；证据截止：${scope.report.snapshot_at}；候选：${scope.report.candidate_ids_json}。` : "";
  const full = scope.report ? `${context}${metadata}\n该版本完整报告：\n${scope.report.content}` : context;
  return full.length <= 8000 ? full : `${context}${metadata}\n报告全文超过本次接口长度，未携带全文；仅依据本次商品证据与报告元信息回答，不声称已理解全报告。`;
}

export function filteredProducts(data: ProjectOverview, params: URLSearchParams, insights: ProductInsights = productInsights(data)) {
  const normalize = (value: string) => value.toLowerCase().replace(/(\d+)\s*g(?:b)?\b/gi, "$1gb");
  const filter = params.get("state") ?? "all", search = params.get("q") ?? "";
  const matchRank = { meets: 0, unknown: 1, unjudged: 2, outside: 3 };
  return [...new Map(data.cards.map(card => [card.listing_id, card])).values()].filter(card => (filter === "all" || card.research_state === filter) && normalize([card.title, `#${card.listing_id}`, card.location, card.seller_name].join(" ")).includes(normalize(search)) && filterInsight(card, insights.items.get(card.listing_id)!, params))
    .sort((a, b) => params.get("sort") === "price" ? (a.price_value ?? Infinity) - (b.price_value ?? Infinity) : params.get("sort") === "match" ? matchRank[insights.items.get(a.listing_id)!.match] - matchRank[insights.items.get(b.listing_id)!.match] || b.listing_id - a.listing_id : params.get("sort") === "ai" ? Number(insights.items.get(b.listing_id)!.candidate) - Number(insights.items.get(a.listing_id)!.candidate) || b.listing_id - a.listing_id : b.listing_id - a.listing_id);
}
export function productAgentScope(data: ProjectOverview, params: URLSearchParams, selected: number[] = []): AgentScope {
  if (selected.length) return { role: "products", ids: [...selected], label: `选中的 ${selected.length} 件商品；不是全部筛选结果` };
  const rows = filteredProducts(data, params);
  return { role: "products", ids: rows.slice(0, 20).map(card => card.listing_id), label: `当前筛选结果前${Math.min(20, rows.length)}件，共${rows.length}件；按当前排序${params.get("display") === "market" ? "；商品库筛选，未带入行情配置筛选" : ""}`, filters: `搜索：${params.get("q") || "不限"}；研究覆盖：${params.get("state") && params.get("state") !== "all" ? productResearchStatus(params.get("state")!).label : "全部状态"}；条件匹配：${matchLabels[params.get("match") as keyof typeof matchLabels] ?? "全部"}；AI判断：${aiLabels[params.get("ai") as keyof typeof aiLabels] ?? "全部"}；排序：${({ price: "价格从低到高", match: "条件匹配优先", ai: "报告候选优先" } as Record<string, string>)[params.get("sort") ?? ""] ?? "最新入库"}` };
}
