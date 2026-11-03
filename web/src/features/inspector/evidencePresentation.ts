import type { ListingEvidence, SellerFields } from "../../api/types";

/** Missing values are availability, never a credit/risk judgment. Keep real 0 and false. */
export function evidenceText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : null;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value !== "string") return null;
  const text = value.trim();
  return !text || /^(none|null|undefined|unknown|nan|n\/a|未知|未记录|暂无|暂无数据|未提供|—|-)$/i.test(text) ? null : text;
}

export function sourceLabel(value?: string | null): string {
  return ({ db: "已保存的平台字段", detail_dom_fallback: "已保存商品页面解析", seller_entered_attribute: "卖家填写的商品属性",
    detail_snapshot: "已保存商品详情", platform_seller_field: "已保存的平台展示", mixed: "多个已保存来源" } as Record<string, string>)[value ?? ""] ?? "来源类型未标注";
}

const sellerLabels: Record<string, string> = {
  seller_credit_level: "平台信用展示", seller_registered_days: "平台注册天数", seller_sold_count: "平台显示已售数量",
  seller_good_rate: "平台显示好评率", seller_realname_verified: "平台实名认证标记", seller_reply_rate_24h: "平台显示24小时回复率",
};
export function sellerFacts(fields: SellerFields) {
  return Object.entries(sellerLabels).flatMap(([key, label]) => {
    const raw = fields[key as keyof SellerFields];
    const value = evidenceText(raw);
    if (value === null) return [];
    return [{ key, label, value: key === "seller_realname_verified" ? (raw === true ? "记录为有认证标记" : raw === false ? "记录为无认证标记" : value) : value,
      source: sourceLabel(fields.field_sources?.[key] ?? fields.data_source) }];
  });
}

export function productQuestions(evidence: ListingEvidence) {
  const questions: string[] = [];
  if (!evidenceText(evidence.search_condition)) questions.push("向卖家确认成色与瑕疵");
  if (!Object.values(evidence.detail?.attributes ?? {}).some(value => evidenceText(value) !== null)) questions.push("向卖家确认关键规格与配件");
  return questions;
}
