import { describe, expect, it } from "vitest";
import type { ProjectCard, ProjectOverview } from "../../api/projectClient";
import type { TaskDetail } from "../../api/types";
import { goalImpact, goalRecordState, impactSummary, initialGoalProposal, memoryMinimum, supportsMemory, type GoalProposal } from "./goalImpact";
const card = (listing_id: number, title: string, price_value: number | null): ProjectCard => ({ listing_id, title, price_value, price_text: null, url: "", location: null, seller_name: null, search_condition: null, detail_status: "not_captured", research_state: "evaluated", source_run_ids: [] });
const proposal: GoalProposal = { goal: "至少16GB，预算不超过5000元，优先M系列", budget: 5000, minimumMemory: 16, hard: [], soft: ["优先M系列"] };
const cards = [card(143, "MacBook Pro M1 Pro 16GB 1TB", 6000), card(385, "MacBook Pro M2 16GB 512GB", 5666), card(378, "MacBook Pro M2 8GB 256GB", 4090), card(366, "MacBook Pro M1 8GB 512GB", 3400)];
describe("goal adjustment read-only impact", () => {
  it("only shows memory for a known computer category with existing applicable data", () => {
    const data = { project: { title: "NS2 Pro手柄", goal: "给MacBook配的手柄" }, policy: { hard: [] }, cards } as unknown as ProjectOverview;
    expect(supportsMemory(data)).toBe(false);
    expect(supportsMemory({ ...data, project: { ...data.project, title: "其他商品", goal: "买个好用的" } })).toBe(false);
    expect(supportsMemory({ ...data, project: { ...data.project, title: "MacBook", goal: "二手MacBook Pro" } })).toBe(true);
    expect(supportsMemory({ ...data, cards: [], project: { ...data.project, title: "MacBook", goal: "二手MacBook Pro" } })).toBe(false);
  });
  it("MacBook acceptance: two prices and two title memory claims fail the proposed conditions", () => {
    const before = JSON.stringify(cards), result = goalImpact(cards, proposal);
    expect(result.map(item => item.kind)).toEqual(["outside", "outside", "outside", "outside"]);
    expect(result.filter(item => item.reasons.some(reason => reason.includes("超出拟定预算")))).toHaveLength(2);
    expect(result.filter(item => item.reasons.some(reason => reason.includes("低于拟定的 16GB")))).toHaveLength(2);
    expect(JSON.stringify(cards)).toBe(before);
  });
  it("missing, ambiguous RAM and VRAM are unknown, never treated as a proven shortfall", () => {
    const result = goalImpact([card(1, "MacBook Pro M2", 4000), card(2, "MacBook Pro M2 8GB 16GB 多种配置", 4000), card(3, "iMac 显卡8GB", 4000), card(4, "16GB 存储卡", 100), card(5, "定金 MacBook Pro M2 32GB", 100)], proposal);
    expect(result.every(item => item.kind === "unknown")).toBe(true);
  });
  it("positive known fields are provisional, and unsupported hard conditions remain unknown", () => {
    const good = card(1, "MacBook Pro M2 32GB 512GB", 4500);
    expect(goalImpact([good], proposal)[0].kind).toBe("meets_known");
    expect(goalImpact([good], { ...proposal, hard: ["无维修"] })[0].kind).toBe("unknown");
    expect(goalImpact([good], { ...proposal, hard: ["", "  "] })[0].kind).toBe("meets_known");
    expect(goalImpact([{ ...good, price_text: "¥4500起" }], proposal)[0].kind).toBe("unknown");
  });
  it("does not infer a hard memory requirement from arbitrary goal text or remove stronger retained constraints", () => {
    expect(memoryMinimum("优先16GB内存")).toBeNull(); expect(memoryMinimum("至少16GB内存且无维修")).toBeNull();
    expect(memoryMinimum("至少32GB内存")).toBe(32);
    expect(goalImpact([card(1, "MacBook Pro M2 16GB", 4000)], { ...proposal, hard: ["至少32GB内存"] })[0].kind).toBe("outside");
    expect(goalImpact([cards[0]], { ...proposal, budget: null, minimumMemory: null })[0].kind).toBe("unknown");
  });
  it("deduplicates counts, limits recommendation impact to known report candidates and preserves favorites", () => {
    const data = { cards: [...cards, cards[0]], report: { candidate_ids_json: "[143,385,378,366,999]" }, favorites: [143] } as unknown as ProjectOverview;
    expect(impactSummary(data, proposal).counts.outside).toBe(4); expect(impactSummary(data, proposal).candidates).toHaveLength(4);
    expect(data.favorites).toEqual([143]);
  });
  it("distinguishes real legacy revisions, unversioned original goals and unavailable status without guessing from run timestamps", () => {
    const data = { project: { goal: "原目标" }, policy: { budget: null, hard: [], soft: [] } } as unknown as ProjectOverview;
    const detail = { task: { effective_goal: "原目标" }, preference_revision_id: 0, preference_revisions: [] } as unknown as TaskDetail;
    expect(goalRecordState(data, detail)).toBe("unversioned");
    expect(goalRecordState(data, { ...detail, preference_revision_id: 3 })).toBe("unlinked");
    expect(goalRecordState(data, { ...detail, task: { ...detail.task, effective_goal: "新目标" } })).toBe("unlinked");
    expect(goalRecordState(data, detail, true)).toBe("unknown"); expect(goalRecordState(data)).toBe("unknown");
    expect(initialGoalProposal(data).minimumMemory).toBeNull();
  });
});
