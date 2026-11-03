import type { ProjectCard } from "../../api/projectClient";
import { extractSpecs } from "../market/marketAnalysis";
import { goalImpact, type GoalImpact, type GoalProposal } from "./goalImpact";

const normalized = (text: string) => text.toLowerCase().replace(/[\s，,。:：·_-]/g, "");
type Check = (card: ProjectCard) => { kind: GoalImpact["kind"]; reason: string };
/** Narrow, auditable title checks. Absence is unknown, never proof of a mismatch. */
function titleCheck(condition: string): Check | null {
  const text = condition.trim(), expectedModel = extractSpecs(text).specs.model;
  const pureModel = expectedModel && normalized(text.replace(/^(?:必须是|机型为|型号为|必须为)/, "")) === normalized(expectedModel);
  const appleM = /^(?:搭载|使用|必须搭载)?\s*(?:Apple|苹果)?\s*M\s*系列(?:芯片|处理器)?$/i.test(text);
  // For other categories, only literal model-like conditions containing letters
  // and a model number are matched. No invented category, aliases or authenticity.
  const literalModel = !expectedModel && text.length <= 64 && /[a-z].*\d|\d.*[a-z]/i.test(text)
    && !/至少|不低于|必须|原装|正品|维修|优先|只|预算|内存|硬盘|成色|电池|[<>≥≤]/.test(text);
  if (!pureModel && !appleM && !literalModel) return null;
  return card => {
    if (/^\s*(?:求购|回收|适用|适配|兼容|出租|租赁)|保护壳|保护套|包装盒|键盘膜|贴膜|维修服务|手柄[壳套]|摇杆帽|收纳包|充电底座/.test(card.title)) return { kind: "unknown", reason: "商品主体或配件身份待核实，不能凭兼容型号判断" };
    const parsed = extractSpecs(card.title);
    if (appleM) {
      if (parsed.ambiguous.includes("chip")) return { kind: "unknown", reason: "芯片描述存在多配置，待核实" };
      if (parsed.specs.chip?.startsWith("Intel") || parsed.specs.chip?.startsWith("Ryzen")) return { kind: "outside", reason: "芯片不符：标题自述为非 Apple M 系列，尚未独立核实" };
      if (parsed.specs.chip?.startsWith("M") && /MacBook|iMac|Mac\s*(?:mini|studio)|苹果|Apple/i.test(card.title)) return { kind: "meets_known", reason: "标题自述为 Apple M 系列，尚未独立核实" };
      return { kind: "unknown", reason: "Apple M 系列芯片证据待核实" };
    }
    if (pureModel) {
      if (parsed.ambiguous.includes("model") || !parsed.specs.model) return { kind: "unknown", reason: "商品机型缺失或多型号，待核实" };
      return normalized(parsed.specs.model) === normalized(expectedModel!) ? { kind: "meets_known", reason: `标题自述为 ${expectedModel}，尚未独立核实` }
        : { kind: "outside", reason: `机型不符：标题自述为 ${parsed.specs.model}，要求 ${expectedModel}` };
    }
    return normalized(card.title).includes(normalized(text)) ? { kind: "meets_known", reason: `标题包含指定型号「${text}」，仅为卖家自述` }
      : { kind: "unknown", reason: `指定型号「${text}」未在标题明确记录，待核实` };
  };
}

export function productConditions(cards: ProjectCard[], proposal: GoalProposal): GoalImpact[] {
  const checks = proposal.hard.map(titleCheck);
  const remaining = proposal.hard.filter((_, index) => !checks[index]);
  const baseActive = proposal.budget !== null || !!proposal.minimumMemory || remaining.some(value => value.trim());
  return goalImpact(cards, { ...proposal, hard: remaining }).map(impact => {
    const extra = checks.filter((check): check is Check => check !== null).map(check => check(impact.card));
    if (!extra.length) return impact;
    const kinds = [...(baseActive ? [impact.kind] : []), ...extra.map(item => item.kind)];
    return { ...impact, kind: kinds.includes("outside") ? "outside" : kinds.includes("unknown") ? "unknown" : "meets_known", reasons: [...(baseActive ? impact.reasons : []), ...extra.map(item => item.reason)] };
  });
}
