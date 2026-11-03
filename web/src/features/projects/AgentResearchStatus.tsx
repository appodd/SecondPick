import type { ProjectOverview } from "../../api/projectClient";
import { ExecutionStatus, SnapshotNotice, StatusBadge, useExecutionStatus } from "../../components/status/ExecutionStatus";
import { researchExecution, researchScheduling } from "../../components/status/statusModel";
import { date } from "./projectUi";

const coverageFields = [
  ["evaluated", "已逐项分析", "当前版本已保存单件商品的结构化 AI 评价；不是累计历史完成量，也不保证每一项信息都已核实。"],
  ["under_ai", "已安排研究", "当前商品版本已纳入研究任务，包含排队与执行；不代表每件商品此刻正在分析，也不等于已完成。"],
  ["waiting", "等待安排", "当前版本尚未纳入研究任务的待分析商品；不代表必然在下一批执行，具体由原有调度决定。"],
  ["needs_information", "信息待补充", "现有信息不足以归入常规可比较样本；不是判定商品不合格，也不等于永远不会研究。"],
  ["summarized", "仅有批次概述", "已参与一批研究，但当前版本没有保存单件结构化评价；不计入已逐项分析。"],
  ["rule_excluded", "规则初筛排除", "当前版本被规则初筛排除，未因此完成 AI 分析。"],
  ["blocked", "研究受阻", "当前版本的研究被标记受阻；具体原因需查看相应任务，不代表商品本身有风险。"],
] as const;
function count(value: number | undefined) { return Number.isSafeInteger(value) && value! >= 0 ? value : "—"; }

export function AgentResearchStatus({ data, compact = false, details, showSchedule = true }: { data: ProjectOverview; compact?: boolean; details?: () => void; showSchedule?: boolean }) {
  const current = researchExecution(data);
  const schedule = researchScheduling(data);
  const visible = useExecutionStatus(current);
  const running = data.studies.filter(study => study.state === "running").length;
  const queued = data.studies.filter(study => study.state === "queued").length;
  const partial = data.studies.length >= 30;
  const latest = data.studies.map(study => study.finished_at).filter((value): value is string => !!value).sort().at(-1);
  if (compact) return <div className="sp-agent-status-summary"><div className="sp-config-status"><strong>Agent 研究</strong><StatusBadge status={current} live />
    {details ? <button className="sp-status-link" onClick={details}>查看研究状态 →</button> : null}</div>
    <p className="sp-status-time">{visible.action ?? visible.reason}</p></div>;
  const active = data.studies.find(study => study.state === "running") ?? data.studies.find(study => study.state === "queued");
  return <>{showSchedule ? <div className="sp-config-status"><StatusBadge status={schedule} live /></div> : null}
    <ExecutionStatus status={current} />
    {active && visible.kind !== "unknown" ? <a className="sp-research-run-link" href={`#research-run-${active.id}`}>查看{active.state === "running" ? "当前" : "排队"}研究详情 →</a> : null}
    <SnapshotNotice />
    {visible.kind === "unknown" ? <p className="sp-status-time">当前执行暂不可确认；以下保留最近读取的覆盖统计。</p> : null}
    <div className="sp-research-status-grid" aria-label="核心研究统计">{coverageFields.slice(0, 3).map(([key, name, hint]) => <div key={key}>
      <b>{count(key === "waiting" && data.research_work ? data.research_work.unassessed : data.coverage[key])}</b><span title={hint} tabIndex={0} aria-description={hint}>{key === "waiting" && data.research_work ? "尚未逐项研究" : name}</span>
    </div>)}</div>
    <p className="sp-status-time">{data.goal_context ? `以上按目标 v${data.goal_context.current_revision} 与当前商品证据版本统计；旧目标研究不计入。` : "以上按商品证据版本统计，尚未关联选购目标版本，不代表已按最新目标完成评估。"}</p>
    {data.research_work ? <div aria-label="后续研究安排" className="sp-status-time">
      <p>{data.research_work.reason}。</p>
      <details className="sp-copy-help"><summary>研究安排说明</summary><p>尚未逐项研究中：可有限补研 {data.research_work.counts.ready} 件 · 需补证据或指定重点 {data.research_work.counts.needs_evidence} 件 · 已排队 {data.research_work.counts.queued} 件 · 正在研究 {data.research_work.counts.running} 件</p><p>这是选样状态，不是进度百分比；账号剩余额度暂不可确认。</p></details>
      {data.research_work.counts.failed + data.research_work.counts.attempted > 0 ? <p>另有 {data.research_work.counts.failed + data.research_work.counts.attempted} 件补研尝试受阻或未形成逐项判断，同证据不自动重试；请查看对应研究记录。</p> : null}
    </div> : null}
    {typeof data.coverage.summarized === "number" && data.coverage.summarized > 0 ? <p className="sp-status-time">另有 {data.coverage.summarized} 件仅有批次概述，尚无逐项评价。</p> : null}
    <details className="sp-research-coverage"><summary>研究覆盖详情</summary>
      <p>统计范围：本项目 {data.total} 件商品的当前版本，每件只归入一个分类；不是历次研究次数的累加。</p>
      <dl>{coverageFields.map(([key, name, hint]) => <div key={key}><dt title={hint} tabIndex={0} aria-description={hint}>{name}</dt><dd>{count(data.coverage[key])} 件</dd></div>)}</dl>
      <p>已安排与已逐项分析不会重复计入当前分类；同目标同证据的有效逐项判断不会被后续摘要或失败覆盖。已研究商品再次执行时保留其已研究分类，任务执行另看上方状态。仅有批次概述、规则排除均不计为逐项分析完成。</p>
      {data.coverage_history ? <p>历史逐项分析 {data.coverage_history.evaluated} 件（商品去重，可能基于旧目标或旧证据）；当前有 {data.coverage_history.reusable_evidence} 件保留了同版研究输入可供复用。不与上方当前目标覆盖相加，不自动视为新目标已评估。</p> : null}
      {data.research_work ? <details><summary>查看选样与跳过原因</summary>
        <p>以下依据目标 v{data.research_work.goal_revision} 和当前证据；每批最多 {data.research_work.batch_limit} 件。收藏、历史提名仅为优先线索，不等于已核实或推荐购买。无明确线索的商品仍可手动选择研究。</p>
        <p>有证据但未有优先线索 {data.research_work.counts.no_priority} 件；预算初筛跳过 {data.research_work.counts.rule_excluded} 件。各选样分类不与研究覆盖统计相加。</p>
        <ul>{data.research_work.items.map(item => <li key={item.listing_id}>#{item.listing_id}：{item.reason}{item.study_id ? <a href={`#research-run-${item.study_id}`}> · 研究 #{item.study_id}</a> : null}</li>)}</ul>
      </details> : null}
      {data.goal_context && data.goal_context.current_revision > 1 ? <p>目标变化可按授权安排一个有限校准批次，不自动全量重研。{data.goal_context.calibration_work?.reason ?? "可手动选择商品研究。"} 当前目标报告生成后，新增证据继续使用既有增量机制。</p> : null}
      <h3>任务与调度</h3>
      <p>{partial ? "最近30次记录中" : "当前已返回记录中"}：{visible.kind === "unknown" ? "执行状态暂不可确认" : `${running} 个运行任务、${queued} 个排队任务`}。任务数量与商品件数口径不同，不相加。</p>
      {partial ? <p>任务列表最多返回最近30次，可能缺少更早的活动任务；不能据此确认完整队列或全部正在分析的商品。</p> : null}
      <p>{partial ? "最近30次记录中的研究结束" : "最近一次研究结束"}：{latest ? date(latest) : "尚无结束记录"}。开始时间与细分进展未提供，不据此计算进度百分比。</p>
      <p>原有样本门槛：{data.policy.minimum}。是否触发研究仍由后端策略决定，“等待安排”不是下一批任务的承诺。</p>
    </details></>;
}
