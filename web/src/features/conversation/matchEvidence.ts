import type { AssessmentBatch } from "../../api/types";

export type Judgment = AssessmentBatch["result"]["assessments"][number]["judgments"][number];
export const matchStatusLabels = { MET: "符合（据当前证据）", NOT_MET: "不符合", UNKNOWN: "未知，待核实", CONFLICT: "证据冲突" };
export const evidenceSourceLabels = { seller_claim: "卖家自述", platform_display: "平台展示", image_observation: "图片依据（使用情况待核对）", user_statement: "用户补充", inference: "AI 推断", missing: "信息缺失" };

/** Provenance is not a verification grade. Never infer authentication from
 * reference count, image URLs, or the model's choice of source_type. */
export function judgmentBasis(item: Judgment) {
  if (!item.evidence_refs.length && item.status !== "UNKNOWN") return "引用依据缺失 · 核验未确认";
  const source = evidenceSourceLabels[item.source_type];
  return item.source_type === "seller_claim" ? `${source} · 实物待核实`
    : item.source_type === "image_observation" ? `${source} · 非独立核验`
    : source ?? "来源未提供";
}

export function assessmentBasis(items: Judgment[]) {
  return [...new Set(items.map(item => evidenceSourceLabels[item.source_type] ?? "来源未提供"))].join("、") || "依据尚未提供";
}
