import type { ProjectCard, ProjectOverview } from "../../api/projectClient";
import type { TaskDetail } from "../../api/types";
import { extractSpecs } from "../market/marketAnalysis";
import { candidateIds } from "./reportCandidates";

export interface GoalProposal { goal: string; budget: number | null; minimumMemory: number | null; hard: string[]; soft: string[] }
export type ImpactKind = "outside" | "unknown" | "meets_known";
export interface GoalImpact { card: ProjectCard; kind: ImpactKind; reasons: string[] }
export function memoryMinimum(text: string): number | null {
  const match = text.trim().match(/^(?:内存\s*(?:至少|不低于|≥|>=)\s*(\d+)\s*(?:GB|G)|(?:至少|不低于|≥|>=)\s*(\d+)\s*(?:GB|G)\s*(?:以上)?\s*内存)$/i);
  return match ? Number(match[1] ?? match[2]) : null;
}
export function initialGoalProposal(data: ProjectOverview): GoalProposal {
  const memory = data.policy.hard.map(memoryMinimum).filter((value): value is number => value !== null);
  return { goal: data.project.goal, budget: data.policy.budget, minimumMemory: memory.length ? Math.max(...memory) : null, hard: [...data.policy.hard], soft: [...data.policy.soft] };
}
export function goalImpact(cards: ProjectCard[], proposal: GoalProposal): GoalImpact[] {
  const hardMemory = proposal.hard.map(memoryMinimum).filter((value): value is number => value !== null);
  const memory = Math.max(proposal.minimumMemory ?? 0, ...hardMemory);
  const unsupported = proposal.hard.filter(text => text.trim() && memoryMinimum(text) === null);
  return [...new Map(cards.map(card => [card.listing_id, card])).values()].map(card => {
    const reasons: string[] = []; let outside = false, unknown = false, checked = 0;
    if (proposal.budget !== null) {
      checked++;
      const usable = !/^\s*(?:求购|回收|出租|租赁|维修服务|维修报价|定金|订金)/.test(card.title) && card.price_value !== null && Number.isFinite(card.price_value) && card.price_value > 0
        && !/起|定金|订金|首付|每[月天]|\/(?:月|天)|\d\s*[-~～至]\s*\d|^\s*[¥￥]?\s*-/.test(card.price_text ?? "");
      if (!usable) { unknown = true; reasons.push("没有可用于核对预算的单件挂牌价"); }
      else if (card.price_value! > proposal.budget) { outside = true; reasons.push("按已保存挂牌价超出拟定预算"); }
      else reasons.push("已保存挂牌价在拟定预算内（不是成交价）");
    }
    if (memory > 0) {
      checked++;
      const parsed = extractSpecs(card.title);
      const memoryContext = /MacBook|iMac|ThinkPad|Mac\s*(?:mini|studio)|笔记本|台式|一体机|运行内存|\bRAM\b|内存(?!卡)/i.test(card.title);
      const ram = memoryContext && parsed.specs.memory ? Number.parseInt(parsed.specs.memory) : null;
      if (ram === null || parsed.ambiguous.includes("memory")) { unknown = true; reasons.push("标题内存缺失、多配置或用途不明确，需要核实"); }
      else if (ram < memory) { outside = true; reasons.push(`按标题自述 ${ram}GB，低于拟定的 ${memory}GB；尚未独立核实`); }
      else reasons.push(`标题自述 ${ram}GB 暂符合内存条件，尚未独立核实`);
    }
    if (unsupported.length) { unknown = true; reasons.push(`另有 ${unsupported.length} 项硬条件不能用现有列表字段自动核对`); }
    if (!checked) { unknown = true; reasons.push("本次没有可自动核对的预算或最低内存条件"); }
    return { card, reasons, kind: outside ? "outside" : unknown ? "unknown" : "meets_known" };
  });
}
export function impactSummary(data: ProjectOverview, proposal: GoalProposal) {
  const items = goalImpact(data.cards, proposal), ids = new Set(candidateIds(data));
  const candidates = items.filter(item => ids.has(item.card.listing_id));
  return { items, candidates, counts: {
    outside: items.filter(item => item.kind === "outside").length,
    unknown: items.filter(item => item.kind === "unknown").length,
    meets_known: items.filter(item => item.kind === "meets_known").length,
  } };
}
export function supportsMemory(data: ProjectOverview) {
  const target = `${data.project.title ?? ""} ${data.project.goal}`;
  if (/手柄|耳机|相机|镜头|手表|存储卡|键盘|鼠标/i.test(target)) return false;
  const computer = /MacBook|iMac|ThinkPad|Mac\s*(?:mini|studio)|笔记本(?:电脑)?|台式(?:电脑|机)|一体机/i.test(target);
  return computer && (data.policy.hard.some(text => memoryMinimum(text) !== null) || data.cards.some(card => !!extractSpecs(card.title).specs.memory));
}
export function goalRecordState(data: ProjectOverview, detail?: TaskDetail, unavailable = false) {
  if (unavailable) return "unknown" as const;
  if (data.goal_context) return data.goal_context.legacy_unmerged ? "unlinked" as const : "unversioned" as const;
  if (unavailable || !detail) return "unknown" as const;
  const revision = Math.max(detail.preference_revision_id ?? 0, ...detail.preference_revisions.map(item => item.id));
  // A legacy revision is real, but ProjectResearch does not consume it or bind reports to it.
  return revision > 0 || detail.task.effective_goal.trim() !== data.project.goal.trim() ? "unlinked" as const : "unversioned" as const;
}
