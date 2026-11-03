import { render, screen, fireEvent, within, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectOverview } from "../../api/projectClient";
import { Overview } from "./Overview";
import { GoalContinuityProvider } from "./GoalContinuity";
const agentOpen = vi.hoisted(() => vi.fn());
beforeEach(()=>vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[],enabled:true,platform_enabled:true,candidate_pool_count:0}),{status:200}))));
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
vi.mock("./ProjectAgent", () => ({ useProjectAgent: () => ({ open: agentOpen }) }));
vi.mock("./OverviewRuntime", () => ({ OverviewRuntime: () => <div>真实运行详情入口</div> }));
vi.mock("../inspector/VisualInvestigation", () => ({ VisualInvestigationPolicy: () => <div>视觉策略详情</div>, VisualInvestigation: () => null }));
vi.mock("../inspector/VisualSummary", () => ({ VisualSummary: () => null }));

function fixture(): ProjectOverview {
  return { project: { id: 1, title: "选购项目", goal: "预算内选购", status: "active" }, policy: { budget: 500, hard: [], soft: [], minimum: 20, paused: 0, auto_research: 0 }, total: 3, eligible: 3, pending: 1, coverage: { evaluated: 2, summarized: 0, waiting: 1, needs_information: 0 }, phase: "incremental", report: { id: 47, study_id: 1, content: "## 综合结论\n\n建议先核实配件，再决定是否购买。", candidate_ids_json: "[12]", snapshot_at: "2026-10-27", created_at: "2026-10-27", limited: 1, evidence_current: true }, cards: [{ listing_id: 12, title: "真实商品标题", price_value: 300, price_text: "300", url: "", location: null, seller_name: null, search_condition: null, detail_status: "unknown", research_state: "evaluated", source_run_ids: [] }], favorites: [], changes: [{ id: 1, content: "报告中的配件仍待确认", created_at: "2026-10-27" }], studies: [], goal_context: { current_revision: 1, original_goal: "预算内选购", report_current: true, calibration: "current", legacy_unmerged: false, updated_at: "2026-10-27", automatic_calibration_supported: true } };
}
function mount(d = fixture()) {
  const go = vi.fn(), select = vi.fn(), action = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><GoalContinuityProvider data={d}><Overview data={d} go={go} select={select} action={action} busy={false}/></GoalContinuityProvider></MemoryRouter></QueryClientProvider>);
  return { go, select, action };
}
describe("overview reading and onward navigation", () => {
  it('keeps page introductions separate from one concrete next action',async()=>{const d=fixture();d.report=null;d.total=0;d.cards=[];d.eligible=0;const {go,action}=mount(d);await screen.findByRole('heading',{name:'目标已保存，下一步设置监控'});expect(screen.queryByRole('list',{name:'选购研究流程'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'新建监控'}));expect(go).toHaveBeenCalledWith('monitors');expect(action).not.toHaveBeenCalled();expect(document.querySelector('.sp-project-guide .sp-guide-next')).toBeNull()});
  it('monitor read failure stays uncertain after the guide is closed',async()=>{vi.mocked(fetch).mockRejectedValue(new Error('offline'));const d=fixture();d.report=null;d.total=0;d.cards=[];d.eligible=0;mount(d);fireEvent.click(screen.getByRole('button',{name:'关闭指南'}));await waitFor(()=>expect(screen.getByRole('heading',{name:'确认商品收集进度'})).toBeVisible());expect(screen.queryByRole('button',{name:'新建监控'})).toBeNull();expect(screen.queryByText('正在积累可比较的样本')).toBeNull()});
  it("routes an unclear goal to the existing goal editor rather than offering research", () => { const d=fixture();d.project.goal='';d.report=null;d.total=0;d.cards=[];mount(d);expect(screen.getByRole('heading',{name:'先确认你的选购目标'})).toBeVisible();expect(screen.getByRole('link',{name:'核对选购目标'})).toHaveAttribute('href',expect.stringContaining('editGoal=1'));expect(screen.queryByRole('button',{name:'和 Agent 梳理采集计划'})).toBeNull(); });
  it("opens with a saved conclusion, keeps operation detail collapsed", () => { mount(); expect(screen.getByText("建议先核实配件，再决定是否购买。")).toBeVisible(); expect(screen.getByText("真实运行详情入口").closest("details")).not.toHaveAttribute("open"); expect(screen.queryByText("视觉策略详情")).toBeNull(); });
  it("opens the existing product evidence with the correct ID", () => { const { select } = mount(); fireEvent.click(screen.getByRole("button", { name: /查看商品与证据/ })); expect(select).toHaveBeenCalledWith(12); });
  it("opens a scoped Agent draft without executing a study", () => { const { action } = mount(); fireEvent.click(screen.getByRole("button", { name: /带着结论继续问/ })); expect(agentOpen).toHaveBeenCalled(); expect(action).not.toHaveBeenCalled(); });
  it("gives an empty project a planning draft rather than a research request with no products", () => { const d=fixture();d.report=null;d.total=0;d.cards=[];const {action}=mount(d);fireEvent.click(screen.getByRole("button",{name:"和 Agent 梳理采集计划"}));expect(agentOpen).toHaveBeenCalledWith(expect.objectContaining({role:"planning",ids:[]}));expect(action).not.toHaveBeenCalled(); });
  it("connects candidates, monitors and products without mutation", () => { const { go, action } = mount(); fireEvent.click(screen.getByRole("button", { name: /候选清单/ })); expect(go).toHaveBeenLastCalledWith("shortlist"); fireEvent.click(screen.getByRole("button", { name: /监控任务/ })); expect(go).toHaveBeenLastCalledWith("monitors"); fireEvent.click(screen.getByRole("button", { name: /全部商品/ })); expect(go).toHaveBeenLastCalledWith("products"); expect(action).not.toHaveBeenCalled(); });
  it("shows stale reports as historical with a visible warning", () => { const d = fixture(); d.report!.evidence_current = false; mount(d); expect(screen.getByText("商品证据已有更新，本结论仍基于原快照。")).toBeVisible(); expect(screen.getByRole("heading", { name: "报告提及的候选" })).toBeVisible(); });
  it("does not turn favorites into AI recommendations before the first report", () => { const d = fixture(); d.report = null; d.favorites = [12]; mount(d); expect(screen.getByRole("heading", { name: "还没有研究候选" })).toBeVisible(); expect(screen.queryByRole("button", { name: /真实商品标题/ })).toBeNull(); });
  it("retains unread changes during a background data refresh", () => { mount(); expect(screen.getByText("报告中的配件仍待确认")).toBeVisible(); });
  it("makes only the explicit read acknowledgement a mutation", () => { const { action } = mount(); fireEvent.click(screen.getByRole("button", { name: "标为已查看" })); expect(action).toHaveBeenCalledTimes(1); });
  it("keeps report detail behind its explicit viewer", () => { mount(); fireEvent.click(screen.getByRole("button", { name: /阅读完整报告/ })); expect(within(screen.getByRole("dialog")).getByText(/建议先核实配件/)).toBeVisible(); });
});
