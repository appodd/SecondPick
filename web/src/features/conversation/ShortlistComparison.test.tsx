import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { CandidateSummary, MessageDto } from "../../api/types";
import { ShortlistComparison, candidateCommentary, comparisonFacts } from "./ShortlistComparison";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const candidate: CandidateSummary = { listing_id: 4721, source_run_ids: [83], url: "https://www.goofish.com/item?id=1",
  title: "个人自用手机 256G", search_description: "上海金桥站自提。", search_description_status: "distinct",
  price_text: "¥4000", price_value: 4000, location: "上海", seller_name: "卖家", search_condition: null, has_detail: false, detail_status: "not_captured" };
const content = "暂选两条，实际机况仍需核实。\n\n1. 4721：4000元，均衡首选。容量和自提地点描述完整。待核实电池循环次数及维修史。\n\n2. 4706：3500元，预算优先。比4721便宜500元。电池具体数值未明确。";

it("associates only a candidate's own paragraph, preserving its concerns", () => {
  expect(candidateCommentary(content, 4706)).toEqual({ reason: "3500元，预算优先。 比4721便宜500元。", checks: ["电池具体数值未明确。"] });
  expect(candidateCommentary("这条可以参考4721。\n\n1. 14721：另一个商品。", 4721)).toEqual({ reason: null, checks: [] });
  expect(candidateCommentary("1. 4721：新增版本补上此前不明确的缺口。优先核实自提时间。", 4721).checks).toEqual(["优先核实自提时间。"]);
});

it("preserves missing, conflicting and negative pickup information without guessing", () => {
  const facts = comparisonFacts({ ...candidate, title: "手机256G或512G", search_description: "不支持自提。", price_text: null }, undefined);
  expect(facts.price).toBe("价格未记录");
  expect(facts.pickup).toBe("不支持自提");
  expect(facts.storage).toBe("256GB / 512GB");
  expect(comparisonFacts({ ...candidate, search_description: "个人自用，无拆修，上海金桥站自提，不议价。" }, undefined).pickup).toBe("上海金桥站自提");
  expect(comparisonFacts(undefined, undefined).storage).toBe("容量未记录");
});

it("loads a late shortlist directly in task scope and opens the selected evidence", async () => {
  const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify({ ...candidate,
    listing_id: url.includes("4706") ? 4706 : 4721, title: url.includes("4706") ? "128GB手机" : candidate.title,
    has_detail: true, detail_status: "captured", detail: { attributes: { 存储容量: url.includes("4706") ? "128GB" : "256GB" } } })));
  vi.stubGlobal("fetch", fetcher);
  const select = vi.fn();
  const message: MessageDto = { id: 17, task_id: 13, operation_id: 8, role: "assistant", content, candidate_ids: [4721, 4706], created_at: "now" };
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ShortlistComparison message={message} candidates={[]} onSelectListing={select} />
  </QueryClientProvider>);
  const first = screen.getByRole("article", { name: "候选 1，商品 4721" });
  expect(await within(first).findByText("256GB")).toBeInTheDocument();
  expect(within(first).getByText("待核实电池循环次数及维修史。")).toBeInTheDocument();
  await userEvent.click(within(first).getByRole("button", { name: /的证据/ }));
  expect(select).toHaveBeenCalledWith(4721);
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(expect.arrayContaining([
    "/api/listings/4721/evidence?task_id=13", "/api/listings/4706/evidence?task_id=13",
  ]));
});

it("keeps saved summary information and an explicit retry when evidence fails", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "unavailable", message: "暂时不可用" } }), { status: 503 })));
  const message: MessageDto = { id: 17, task_id: 13, operation_id: 8, role: "assistant", content, candidate_ids: [4721], created_at: "now" };
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ShortlistComparison message={message} candidates={[candidate]} onSelectListing={() => {}} />
  </QueryClientProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("详情暂时无法加载");
  expect(screen.getByText("¥4000")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
});
