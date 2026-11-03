import { describe, expect, it } from "vitest";
import type { ProjectOverview } from "../../api/projectClient";
import { agentInstruction, candidateIds, defaultAgentScope, productAgentScope } from "./agentContext";
const data = { cards: Array.from({ length: 30 }, (_, i) => ({ listing_id: i + 1, title: i % 2 ? "Intel 16GB" : "M2 16GB", price_value: 1000 + i, research_state: "waiting" })), favorites: [1, 2], policy: { paused: 0, auto_research: 1 }, total: 30, coverage: { waiting: 20, summarized: 10 }, studies: [], report: { id: 9, candidate_ids_json: "[1,2,999]", content: "完整报告证据", snapshot_at: "2026-10-23" } } as unknown as ProjectOverview;
describe("unified Agent scope", () => {
  it("only accepts existing candidate IDs and handles invalid report JSON", () => {
    expect(candidateIds(data)).toEqual([1, 2]);
    expect(candidateIds({ ...data, report: { ...data.report!, candidate_ids_json: "{}" } })).toEqual([]);
    expect(candidateIds({ ...data, report: { ...data.report!, candidate_ids_json: "bad" } })).toEqual([]);
  });
  it("uses current filters and sort for unselected products; selected IDs are never silently truncated", () => {
    const scope = productAgentScope(data, new URLSearchParams("q=Intel&sort=price"));
    expect(scope.ids).toEqual(Array.from({ length: 15 }, (_, i) => (i + 1) * 2));
    expect(scope.filters).toContain("Intel");
    expect(productAgentScope(data, new URLSearchParams(), data.cards.map(c => c.listing_id)).ids).toHaveLength(30);
    expect(productAgentScope(data, new URLSearchParams()).ids).toEqual(Array.from({ length: 20 }, (_, i) => 30 - i));
  });
  it("deduplicates candidate/favorite scopes while leaving oversized scope visible for user selection", () => {
    expect(defaultAgentScope(data, "shortlist").ids).toEqual([1, 2]);
    expect(defaultAgentScope({ ...data, favorites: data.cards.map(c => c.listing_id) }, "shortlist").ids).toHaveLength(30);
    expect(defaultAgentScope(data, "monitors").ids).toEqual([]);
  });
  it("research management includes real coverage and scheduler context without inventing progress", () => {
    const request = agentInstruction(defaultAgentScope(data, "research"), "本次重点");
    expect(request).toContain('"waiting":20'); expect(request).toContain('"auto_research":1'); expect(request).toContain("不据此推断完整队列或完成百分比");
  });
  it("passes complete report version and evidence cutoff when within API limit", () => {
    const request = agentInstruction(defaultAgentScope(data, "overview"), "解释依据");
    expect(request).toContain("完整报告证据"); expect(request).toContain("证据截止：2026-10-23");
    expect(request).toContain("不得更改持久研究策略、监控、收藏");
  });
  it("omits the whole oversized report and discloses that limitation", () => {
    const scope = defaultAgentScope({ ...data, report: { ...data.report!, content: "不可截断".repeat(3000) } }, "overview");
    const request = agentInstruction(scope, "解释依据");
    expect(request.length).toBeLessThanOrEqual(8000); expect(request).toContain("报告全文超过"); expect(request).not.toContain("不可截断");
  });
});
