import { describe, expect, it } from "vitest";
import type { ProjectOverview, Report } from "../../api/projectClient";
import { overviewReport, reportCandidateIds, reportConclusion } from "./overviewReport";

const research = { criteria: [{ criterion_id: "repair", priority: "hard", description: "维修史" }], assessments: [
  { listing_id: 1, conclusion: "conditional", summary: "可以继续核实第一件。", judgments: [{ criterion_id: "repair", status: "UNKNOWN", reason: "第一件缺维修记录", source_type: "missing", evidence_refs: [] }] },
  { listing_id: 2, conclusion: "conditional", summary: "可以继续核实第二件。", judgments: [{ criterion_id: "repair", status: "CONFLICT", reason: "第二件维修记录相互冲突", source_type: "seller_claim", evidence_refs: ["a", "b"] }] },
] };
function data() { return { report: { id: 1, study_id: 4, candidate_ids_json: "[1,2]", content: "当前报告内容", snapshot_at: "2026-10-22T00:00:00Z" },
  cards: [{ listing_id: 1 }, { listing_id: 2 }], studies: [{ id: 4, kind: "initial", state: "completed", listing_ids: [1, 2], snapshot_at: "2026-10-22T00:00:00Z", result: { content: "当前报告内容", research } }] } as unknown as ProjectOverview; }

describe("overview report evidence projection", () => {
  it("retains the complete explicit multi-candidate recommendation in a real-style report opening", () => {
    const opening = "当前建议保持：优先核对商品 #2378；只要单手柄、希望少花钱选商品 #1877。";
    expect(reportConclusion(opening + "新增商品尚不能替代这些方案。\n\n详细依据。")).toBe(opening);
    expect(reportConclusion("当前建议保持：如果预算足够，可选商品 #1。")).toBeNull();
  });
  it("quotes a complete explicit conclusion, never the first N characters", () => {
    expect(reportConclusion("背景说明。\n\n## 综合结论\n\n建议先核实维修情况。\n\n很长的后文。")).toBe("建议先核实维修情况。");
    expect(reportConclusion("**综合结论：** 目前证据不足，暂不建议下单。\n\n其他内容。")).toBe("目前证据不足，暂不建议下单。");
  });
  it("can quote a clearly marked overall decision from the introduction without copying candidate routes", () => {
    expect(reportConclusion("保留商品 #1 和 #2 两条路线。现有证据支持继续核实，尚不足以直接下单。\n\n商品详情很多。")).toBe("现有证据支持继续核实，尚不足以直接下单。");
  });
  it("declines arbitrary, conditional, long and later product-specific narrative", () => {
    expect(reportConclusion("一个冗长的报告开头，尚无完整结论")).toBeNull();
    expect(reportConclusion("现有证据中，如果预算充足则建议下单。")).toBeNull();
    expect(reportConclusion("现有证据" + "较长内容".repeat(60) + "建议核实。")).toBeNull();
    expect(reportConclusion("背景说明。\n\n现有证据建议购买某一商品。")).toBeNull();
    expect(reportConclusion("结论性资料来自卖家，不构成结论。\n\n正文。")).toBeNull();
    expect(reportConclusion("## 商品一\n\n### 结论\n\n建议优先比较此商品。")).toBeNull();
  });
  it("treats corrupt candidate lists as unavailable, not as a zero-candidate recommendation", () => {
    expect(reportCandidateIds({ candidate_ids_json: "bad" } as Report)).toBeNull();
    expect(reportCandidateIds({ candidate_ids_json: "[1,1,2]" } as Report)).toEqual([1, 2]);
    expect(reportCandidateIds({ candidate_ids_json: '["1"]' } as Report)).toBeNull();
  });
  it("uses the report's own study and retains the real reason and uncertainty", () => {
    const value = overviewReport(data());
    expect(value.candidates[0].assessment?.summary).toBe("可以继续核实第一件。");
    expect(value.concerns.map(item => item.reason)).toEqual(["第二件维修记录相互冲突", "第一件缺维修记录"]);
  });
  it("does not attribute unrelated selected questions or newer batches to the current report", () => {
    const value = data(); value.report!.study_id = 99;
    value.studies.unshift({ ...value.studies[0], id: 99, kind: "selected" });
    expect(overviewReport(value).study).toBeUndefined();
    expect(overviewReport(value).concerns).toEqual([]);
  });
  it("requires an exact snapshot and content match if an older response omitted study_id", () => {
    const value = data(); delete value.report!.study_id;
    expect(overviewReport(value).study?.id).toBe(4);
    value.studies[0].result!.content = "不同报告";
    expect(overviewReport(value).study).toBeUndefined();
  });
  it("does not turn later, noncandidate or unavailable judgments into current candidate risks", () => {
    const value = data(); value.report!.candidate_ids_json = "[1]";
    expect(overviewReport(value).concerns.map(item => item.listingId)).toEqual([1]);
    value.report!.candidate_ids_json = "bad";
    expect(overviewReport(value).concerns).toEqual([]);
  });
  it("retains a nominated ID when its current product record is unavailable", () => {
    const value = data(); value.cards = [];
    expect(overviewReport(value).candidates[0]).toMatchObject({ id: 1, card: undefined });
  });
  it("keeps the no-report state free of candidates and invented conclusions", () => {
    const value = data(); value.report = null;
    expect(overviewReport(value)).toMatchObject({ ids: [], candidates: [], concerns: [], conclusion: null });
  });
});
