import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ListingEvidence, SellerFields, TaskDetail } from "../../api/types";
import type { ProjectOverview } from "../../api/projectClient";
import { evidenceText, sellerFacts } from "./evidencePresentation";
import { SellerEvidenceFacts } from "./SellerEvidenceFacts";
import { ListingResearchSummary } from "./ListingResearchSummary";
import { ListingEvidencePanel } from "./ListingEvidencePanel";

afterEach(cleanup);
const fields = { seller_credit_level: null, seller_registered_days: null, seller_sold_count: null, seller_good_rate: null,
  seller_realname_verified: null, seller_reply_rate_24h: null, data_source: "none", field_sources: {}, independently_verified: false } as SellerFields;
const evidence = { listing_id: 1, title: "商品一", url: "https://www.goofish.com/item?id=1", price_value: 100, price_text: "100", detail_status: "not_captured",
  detail: null, search_description: null, search_description_status: "missing", source_run_ids: [1], seller_fields: fields, seller_other_items: [], evidence_conflicts: [],
  collection_state: { detail_snapshot_count: 0, valid_detail_snapshot_count: 0, blocked_detail_snapshot_count: 0, listing_lifetime_product_image_count: 0, listing_lifetime_downloaded_product_image_count: 0, listing_lifetime_ocr_result_count: 0 } } as unknown as ListingEvidence;
const structured = { criteria: [{ criterion_id: "memory", description: "内存16GB", priority: "hard", source_message_ids: [], source_refs: ["task_goal"] }],
  assessments: [{ listing_id: 1, conclusion: "insufficient_evidence", summary: "卖家未提供足够配置凭证", judgments: [{ criterion_id: "memory", status: "UNKNOWN", source_type: "missing", reason: "未见内存截图", evidence_refs: [] }] }] } as const;
function project(result: unknown = null) { return { cards: [{ listing_id: 1, research_state: "summarized" }],
  studies: [{ id: 1, kind: "initial", state: "completed", listing_ids: [1], snapshot_at: "2026-10-22T00:00:00Z", result: { content: "批次研究文字", candidate_ids: [1], research: result } }],
  report: { candidate_ids_json: "[1]", content: "多件商品的批次报告" } } as unknown as ProjectOverview; }

describe("evidence availability and selection semantics", () => {
  it("hides missing tokens without hiding real zero or false", () => {
    for (const value of [null, undefined, "none", "NULL", "undefined", "暂无", "unknown", "  ", NaN, {}]) expect(evidenceText(value)).toBeNull();
    expect(evidenceText(0)).toBe("0"); expect(evidenceText(false)).toBe("否");
    expect(sellerFacts({ ...fields, seller_sold_count: 0, seller_realname_verified: false })).toEqual(expect.arrayContaining([
      expect.objectContaining({ value: "0" }), expect.objectContaining({ value: "记录为无认证标记" }),
    ]));
  });
  it("reads real imported seller fields even when structured fields are empty", () => {
    render(<SellerEvidenceFacts evidence={evidence} profile={{ 卖家注册时长: "来闲鱼9年", 作为卖家的好评率: "100.00%", "卖家在售/已售商品数": "23", 卖家芝麻信用: "暂无" }} />);
    expect(screen.getByText("100.00%")).toBeVisible(); expect(screen.getByText("来闲鱼9年")).toBeVisible();
    expect(screen.getByText("平台在售/已售商品数（原字段）")).toBeVisible();
    expect(screen.queryByText("平台信用展示")).not.toBeInTheDocument();
  });
  it("groups unavailable seller fields and keeps diagnostics closed", () => {
    render(<ListingEvidencePanel evidence={evidence} />);
    expect(screen.queryByText("未记录")).not.toBeInTheDocument(); expect(screen.queryByText("实名认证")).not.toBeInTheDocument();
    expect(screen.getByText(/尚无可用的卖家研究结论/)).toBeVisible();
    expect(screen.getByText("详细证据与采集记录").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("详情快照记录")).not.toBeVisible();
    expect(screen.queryByText(/向卖家索取可核验/)).toBeNull();
  });
  it("renders previously ignored descriptions and separates seller claims from platform fields", () => {
    render(<ListingEvidencePanel evidence={{ ...evidence, detail_status: "captured", detail: { snapshot_id: 8, run_id: 1, description: "自用机器，屏幕有划痕", attributes: { 内存: "16GB", 无效字段: "None" }, attributes_source: "seller_entered_attribute", evidence_source: "seller_entered_attribute", independently_verified: false } }} />);
    expect(screen.getByText("自用机器，屏幕有划痕")).toBeVisible();
    expect(screen.getByText(/详情中的卖家自述/)).toBeVisible(); expect(screen.queryByText("None")).toBeNull();
    expect(screen.getByText(/详情属性未独立验证/)).toBeVisible();
  });
  it("distinguishes blocked access from an unattempted detail capture", () => {
    const { rerender } = render(<ListingEvidencePanel evidence={evidence} />);
    expect(screen.getByText(/尚未采集到有效商品详情/)).toBeVisible();
    rerender(<ListingEvidencePanel evidence={{ ...evidence, detail_status: "blocked" }} />);
    expect(screen.getByText(/详情访问未成功/)).toBeVisible();
    expect(screen.queryByText(/卖家信用差$/)).toBeNull();
  });
  it("does not turn candidate membership or batch summary into a per-product recommendation reason", () => {
    render(<ListingResearchSummary evidence={evidence} project={project()} />);
    expect(screen.getByText(/未提供可单独归属本商品的结构化推荐理由/)).toBeVisible();
    expect(screen.getByText(/曾纳入批次概述/)).toBeVisible();
    expect(screen.getByText("多件商品的批次报告")).not.toBeVisible();
  });
  it("shows saved structured uncertainty without converting missing evidence into a failed requirement", () => {
    render(<ListingResearchSummary evidence={evidence} project={project(structured)} />);
    expect(screen.getByText("证据不足，暂不能判断")).toBeVisible();
    expect(screen.getByText("未见内存截图")).toBeVisible(); expect(screen.getByText("未知，待核实 · 信息缺失")).toBeVisible();
    expect(screen.queryByText("不符合当前要求")).toBeNull();
    expect(screen.getByText(/接口尚未提供逐项校验/)).toBeVisible();
  });
  it("finds older saved per-product judgments when a later batch only has narrative text", () => {
    const data = project(structured); data.studies.unshift({ ...data.studies[0], id: 2, result: { content: "新的批次概述", candidate_ids: [] } });
    render(<ListingResearchSummary evidence={evidence} project={data} />);
    expect(screen.getByText("未见内存截图")).toBeVisible();
  });
  it("respects stale legacy assessments instead of presenting them as current findings", () => {
    const task = { preference_revision_id: 2, preference_revisions: [], research: { assessment_batches: [{ id: 1, preference_revision_id: 1,
      stale: false, result: structured, created_at: "2026-10-22T00:00:00Z", evidence_refs: {} }] } } as unknown as TaskDetail;
    render(<ListingResearchSummary evidence={evidence} task={task} />);
    expect(screen.getByText(/历史判断：要求或商品证据已变化/)).toBeVisible();
    expect(screen.getByText("未见内存截图")).toBeVisible();
    expect(screen.queryByText(/判断的要求与证据仍适用/)).toBeNull();
  });
});


it("old-goal item assessments and recommendations remain explicitly historical after a goal change", () => {
  const data = project(structured);
  data.goal_context = { current_revision: 2, original_goal: "原目标", report_current: false, calibration: "pending", legacy_unmerged: false, automatic_calibration_supported: false, updated_at: "2026-10-23" };
  data.studies[0].goal_revision = 1;
  render(<ListingResearchSummary evidence={evidence} project={data} />);
  expect(screen.getByText(/历史报告曾将此商品列为候选/)).toBeVisible();
  expect(screen.getByText(/历史判断：/, { selector: ".le-conclusion strong" })).toBeVisible();
  expect(screen.queryByText(/当前项目报告将此商品列为 AI 候选/)).not.toBeInTheDocument();
});


it("a current goal's real per-item assessment is preferred over historical judgments", () => {
  const data = project(structured);
  data.goal_context = { current_revision: 2, original_goal: "原目标", report_current: true, calibration: "current", legacy_unmerged: false, automatic_calibration_supported: false, updated_at: "2026-10-23" };
  data.studies[0].goal_revision = 2; data.cards[0].research_state = "evaluated";
  render(<ListingResearchSummary evidence={evidence} project={data} />);
  expect(screen.getByText(/当前项目报告将此商品列为 AI 候选/)).toBeVisible();
  expect(screen.queryByText(/历史判断：/, { selector: ".le-conclusion strong" })).not.toBeInTheDocument();
});
