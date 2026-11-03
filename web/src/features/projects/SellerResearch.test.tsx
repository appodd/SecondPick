import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { projectApi, type SellerProfile, type Study } from "../../api/projectClient";
import { SellerResearch } from "./SellerResearch";

vi.mock("../../api/projectClient", () => ({ projectApi: { seller: vi.fn(), studySeller: vi.fn() } }));
afterEach(cleanup);
const saved: SellerProfile = { seller_id: "123", profile: { 卖家注册时长: "来闲鱼9年", 作为卖家的好评率: "99%", 卖家芝麻信用: "none" },
  observed_at: "2026-10-22T00:00:00Z", researched_at: null, result: null, fresh: false };
function show(studies: Study[] = []) {
  return render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <SellerResearch id={1} listing={1} studies={studies} />
  </QueryClientProvider></MemoryRouter>);
}
beforeEach(() => { vi.resetAllMocks(); vi.mocked(projectApi.seller).mockResolvedValue(saved); vi.mocked(projectApi.studySeller).mockResolvedValue({ id: 3 }); });

describe("seller research states and evidence", () => {
  it("shows available imported fields before research and never triggers research from reading", async () => {
    show();
    expect(await screen.findByText("99%")).toBeVisible();
    expect(screen.getByText("来闲鱼9年")).toBeVisible();
    expect(screen.getByText("尚无已完成的卖家研究结论。")).toBeVisible();
    expect(screen.getByText(/没有完整调查尝试记录/)).toBeVisible();
    expect(screen.queryByText("none")).toBeNull(); expect(projectApi.studySeller).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "分析已保存的卖家资料" }));
    await waitFor(() => expect(projectApi.studySeller).toHaveBeenCalledExactlyOnceWith(1, 1));
    expect(await screen.findByText(/AgentRun #3 已受理/)).toBeVisible();
  });
  it("separates investigated but inconclusive findings, actual clues and unknowns", async () => {
    vi.mocked(projectApi.seller).mockResolvedValue({ ...saved, result: { business_tendency: "unknown", reason: "公开信息太少", risk_clues: [], unknowns: ["维修史待确认", "null"] }, researched_at: "2026-10-22T00:10:00Z" });
    show();
    expect(await screen.findByText("已分析，经营倾向证据仍不足")).toBeVisible();
    expect(screen.getByText("本次研究未列出具体疑点，不代表没有风险。")).toBeVisible();
    expect(screen.getByText("维修史待确认")).toBeVisible(); expect(screen.queryByText("null")).toBeNull();
    expect(screen.getByText(/历史研究档案已过期/)).toBeVisible();
  });
  it("reports pending work truthfully without treating it as active execution", async () => {
    const running = { id: 2, kind: "seller:123", state: "queued", listing_ids: [1] } as Study;
    show([running]);
    expect(await screen.findByText("研究任务排队中")).toHaveAttribute("data-kind", "waiting");
    expect(screen.getByRole("button", { name: "已有卖家研究任务" })).toBeDisabled();
    expect(document.querySelector('[data-kind="running"]')).toBeNull();
  });
  it("does not describe an unreadable seller record as uninvestigated", async () => {
    vi.mocked(projectApi.seller).mockRejectedValue(new Error("unavailable"));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("不能据此判断研究是否完成");
    expect(screen.queryByText("尚无已完成的卖家研究结论。")).toBeNull();
    expect(screen.queryByRole("button", { name: "分析已保存的卖家资料" })).toBeNull();
  });
  it("does not turn an execution failure into a negative credit judgment", async () => {
    show([{ id: 3, kind: "seller:123", state: "failed", listing_ids: [1], error: "CLI unavailable" } as Study]);
    expect(await screen.findByText("本次研究需要处理")).toHaveAttribute("data-kind", "attention");
    expect(screen.getByText(/执行失败不是卖家信用结论/)).toBeVisible();
    expect(screen.getByText("99%")).toBeVisible();
  });
  it("prevents nickname-only seller association when the public ID is absent", async () => {
    vi.mocked(projectApi.seller).mockResolvedValue({ ...saved, seller_id: null, profile: {} });
    show();
    expect(await screen.findByText(/不能按昵称合并档案/)).toBeVisible();
    expect(screen.getByRole("button", { name: "分析已保存的卖家资料" })).toBeDisabled();
  });
});
