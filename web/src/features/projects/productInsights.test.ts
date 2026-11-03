import { describe, expect, it } from "vitest";
import type { ProjectCard, ProjectOverview } from "../../api/projectClient";
import { productInsights } from "./productInsights";
import { filteredProducts, productAgentScope } from "./agentContext";
import { projectReturn } from "./contextNavigation";

function card(id: number, title: string, price: number | null, state = "waiting"): ProjectCard {
  return { listing_id: id, title, price_value: price, price_text: price === null ? null : `¥${price}`, research_state: state, source_run_ids: [], url: "", location: "广州", seller_name: "卖家", search_condition: null, detail_status: "not_captured" };
}
function data(): ProjectOverview {
  return { project: { id: 1, title: "MacBook Pro", goal: "买 MacBook Pro", status: "active" }, policy: { budget: 5000, hard: ["内存至少16GB"], soft: ["上海优先"], paused: 0, auto_research: 0, minimum: 2 },
    cards: [card(1, "MacBook Pro M2 16GB 512GB", 4500, "evaluated"), card(2, "MacBook Pro M2 8GB 256GB", 4000), card(3, "MacBook Pro M2 16GB 512GB", 6000), card(4, "MacBook Pro M2 512GB", 4000, "summarized"), card(5, "MacBook Pro M2 16GB 512GB", null)],
    goal_context: { current_revision: 2, original_goal: "买 MacBook Pro", report_current: true, calibration: "current", legacy_unmerged: false, updated_at: "", automatic_calibration_supported: true },
    studies: [{ id: 1, kind: "initial", state: "completed", goal_revision: 2, listing_ids: [1, 4], snapshot_at: "", created_at: "", error: null, result: { content: "有限批次", candidate_ids: [1, 4], research: { criteria: [], assessments: [{ listing_id: 1, conclusion: "consider", summary: "配置和价格可考虑；机况待核实", judgments: [] }] } } }],
    report: { id: 1, content: "有限报告", candidate_ids_json: "[1,4,4,999]", goal_revision: 2, snapshot_at: "", created_at: "", limited: 1 }, favorites: [], coverage: {}, total: 5, pending: 0, eligible: 0, comparison_groups: {}, changes: [], phase: "incremental" } as ProjectOverview;
}

describe("current-goal product insights", () => {
  it("MacBook: mutually exclusive, deduplicated counts and independent report candidates", () => {
    const source = data(); source.cards.push(source.cards[0]); const before = JSON.stringify(source);
    const result = productInsights(source);
    expect(result.total).toBe(5);
    expect(result.counts).toEqual({ meets: 1, outside: 2, unknown: 2, unjudged: 0 });
    expect(Object.values(result.counts).reduce((a, b) => a + b)).toBe(result.total);
    expect(result.candidateCount).toBe(2);
    expect(result.items.get(2)?.reason).toContain("内存不足");
    expect(result.items.get(3)?.reason).toContain("超过预算");
    expect(result.items.get(1)?.detail).toContain("卖家自述不等于独立核实");
    expect(result.items.get(4)?.candidate).toBe(true);
    expect(result.items.get(4)?.assessment).toBeUndefined();
    expect(result.items.get(4)?.aiDetail).toContain("不等于逐项分析");
    expect(JSON.stringify(source)).toBe(before);
  });
  it("NS2 controller: no computer inference, originality remains unknown and budget contradictions win", () => {
    const source = data();
    source.project = { ...source.project, title: "NS2 Pro手柄", goal: "买原装手柄" };
    source.policy = { ...source.policy, budget: 400, hard: ["必须原装"], soft: [] };
    source.cards = [card(1, "NS2 Pro 原装手柄", 300), card(2, "NS2 Pro 手柄", 500), card(3, "NS2 Pro 手柄", null)];
    const result = productInsights(source);
    expect(result.counts).toEqual({ meets: 0, outside: 1, unknown: 2, unjudged: 0 });
    expect(result.items.get(1)?.reason).toContain("原装性");
    expect([...result.items.values()].some(item => item.reason.includes("内存"))).toBe(false);
  });
  it("reuses known model/chip title adapters and literal controller models without treating missing fields as failure", () => {
    const source = data(); source.policy = { ...source.policy, budget: null, hard: ["MacBook Pro", "搭载 Apple M 系列芯片"] };
    source.cards = [card(1, "MacBook Pro M2 16GB", 4000), card(2, "MacBook Pro Intel i7", 3000), card(3, "MacBook Pro", 3000), card(4, "MacBook Pro M1 M2 多配置", 3000), card(5, "MacBook Pro M2保护壳", 30)];
    expect(productInsights(source).counts).toEqual({ meets: 1, outside: 1, unknown: 3, unjudged: 0 });
    source.policy.hard = ["NS2 Pro 手柄"];
    source.cards = [card(1, "NS2 Pro手柄 日版", 300), card(2, "Switch Pro 手柄", 300), card(3, "NS2 Pro手柄壳", 30)];
    expect(productInsights(source).counts).toEqual({ meets: 1, outside: 0, unknown: 2, unjudged: 0 });
    expect(productInsights(source).items.get(1)?.detail).toContain("卖家自述");
  });
  it("no explicit hard conditions or unconfirmed versions do not invent judgments", () => {
    const source = data(); source.policy = { ...source.policy, budget: null, hard: [], soft: ["优先16GB内存"] };
    expect(productInsights(source).counts.unjudged).toBe(5);
    expect(productInsights(data(), false).counts.unjudged).toBe(5);
    const unlinked = data(); unlinked.goal_context!.legacy_unmerged = true;
    expect(productInsights(unlinked).counts.unjudged).toBe(5);
    expect(productInsights(unlinked).candidateCount).toBe(0);
  });
  it("changed goal or changed evidence never promotes old item conclusions or report membership", () => {
    const source = data(); source.goal_context!.current_revision = 3; source.policy.budget = 4200;
    let result = productInsights(source);
    expect(result.candidateCount).toBe(0);
    expect(result.items.get(1)?.assessment).toBeUndefined();
    expect(result.items.get(1)?.match).toBe("outside");
    source.goal_context!.current_revision = 2;
    for (const state of ["waiting", "queued", "summarized", "blocked"]) {
      source.cards[0].research_state = state;
      expect(productInsights(source).items.get(1)?.assessment).toBeUndefined();
    }
    source.cards[0].research_state = "evaluated"; source.studies = []; source.report = null;
    result = productInsights(source);
    expect(result.items.get(1)?.aiDetail).toContain("最近30次");
    expect(filteredProducts(source, new URLSearchParams("ai=unresearched")).some(item => item.listing_id === 1)).toBe(false);
  });
  it("match, AI, coverage, text, sorts and Agent scope use the same data and survive context returns", () => {
    const source = data();
    expect(filteredProducts(source, new URLSearchParams("match=outside&sort=price")).map(item => item.listing_id)).toEqual([2, 3]);
    expect(filteredProducts(source, new URLSearchParams("ai=consider")).map(item => item.listing_id)).toEqual([1]);
    expect(filteredProducts(source, new URLSearchParams("ai=candidate&state=summarized")).map(item => item.listing_id)).toEqual([4]);
    expect(filteredProducts(source, new URLSearchParams("sort=match"))[0].listing_id).toBe(1);
    expect(productAgentScope(source, new URLSearchParams("match=outside&sort=price")).ids).toEqual([2, 3]);
    const url = "/projects/1?view=products&display=cards&match=outside&ai=all&sort=match&page=1";
    const back = projectReturn(1, url).href;
    expect(back).toContain("match=outside"); expect(back).toContain("ai=all");
  });
});
