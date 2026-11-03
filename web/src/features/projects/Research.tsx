import { useGoalContinuity } from "./GoalContinuity";
import { ReportHistory } from "./ReportHistory";
import { ReportScopeSummary } from "./ReportScopeSummary";
import { projectApi, type ProjectOverview } from "../../api/projectClient";
import { Panel, date } from "./projectUi";
import { AgentResearchStatus } from "./AgentResearchStatus";
import { StatusBadge, useExecutionStatus } from "../../components/status/ExecutionStatus";
import { studyStatus, researchScheduling, researchExecution } from "../../components/status/statusModel";
import { useProjectAgent } from "./ProjectAgent";
import { defaultAgentScope } from "./agentContext";
import { Investigations } from "./Investigations";
import { EvidenceChanges } from "./EvidenceChanges";
import { ConditionJudgments } from "../conversation/ConditionJudgments";
import { VisualEvidence } from "../inspector/VisualEvidence";
import { visualQuestionScope } from "../inspector/visualQuestion";
import {useState} from 'react';
import {researchOrigin,researchPurpose,researchConclusion} from './researchPresentation';

export function Research({
  data,
  action,
  busy,
  select,
}: {
  data: ProjectOverview;
  action: (fn: () => Promise<unknown>) => Promise<void>;
  busy: boolean;
  select?: (listing: number) => void;
}) {
  const agent = useProjectAgent();
  const execution = useExecutionStatus(researchExecution(data));
  const [origin,setOrigin]=useState('all');
  const goalUnavailable = useGoalContinuity().state !== "unversioned";
  const textual = data.studies.filter(study => study.kind !== "visual");
  const latest = textual.find(study => study.state === "completed" && study.result && study.goal_revision === data.goal_context?.current_revision)
    ?? textual.find(study => study.goal_revision === data.goal_context?.current_revision)
    ?? textual.find(study => study.state === "completed" && study.result) ?? textual[0];
  return (
    <>
      <Panel variant="emphasis" className="sp-research-answer sp-research-featured">
        <div className="sp-between"><h2>{latest?.result ? "本次研究答复" : latest ? "当前研究" : "开始一次研究"}</h2>{latest ? <StatusBadge status={studyStatus(latest)} live={["queued", "running"].includes(latest.state)} /> : null}</div>
        {latest ? <><p className="sp-muted">{researchOrigin(latest)} · 研究 #{latest.id} · {latest.listing_ids.length} 件 · {date(latest.finished_at ?? latest.created_at)}{latest.goal_revision !== data.goal_context?.current_revision ? " · 历史目标结果" : ""}</p>{researchPurpose(latest)?<details><summary>为什么研究这些商品</summary><p>{researchPurpose(latest)}</p></details>:null}{latest.result ? <><p className="sp-report-content">{researchConclusion(latest.result.content)}</p><details><summary>完整答复与限制</summary><p className="sp-report-content">{latest.result.content}</p></details></> : <p role="status">{latest.error ? '本次研究未完成，已有证据仍可查看。详情见执行记录。' : latest.state === "queued" ? "等待执行，可继续浏览商品。" : latest.state === "running" ? "正在分析已保存的商品证据。" : "暂无可用答复，请查看下方执行记录。"}</p>}<div className="sp-actions">{latest.listing_ids.map(id => <button key={id} onClick={() => select?.(id)}>查看商品 #{id}</button>)}{latest.result ? <button onClick={() => agent.open({ role: "interpret", ids: latest.listing_ids, label: `研究 #${latest.id} 的商品范围`, question: "这些结论中，最值得向卖家核实的是什么？", studyId: latest.id, researchContext: latest.result!.content.slice(0, 3000) })}>继续追问</button> : null}</div></> : <p>还没有研究结果。可以先浏览商品，或通过 Agent 发起一次研究。</p>}
        <small className="sp-muted">单次研究结果，非全项目综合结论。</small>
        {latest?.result?.check_suggestions?.length ? <section className="ua-open-questions"><h3>仍需核实</h3><ul>{latest.result.check_suggestions.slice(0,3).map((q,i)=><li key={i}>商品 #{q.listing_id}：{q.question}</li>)}</ul><small className="sp-muted">调查建议，尚未向卖家提问或完成核实。</small></section>:null}
      </Panel>
      <Panel>
        <div className="sp-between">
          <div className="sp-config-status"><h2>研究安排</h2><StatusBadge status={researchScheduling(data)} live /></div>
          <button
            disabled={busy}
            onClick={() =>
              action(() =>
                projectApi.control(
                  data.project.id,
                  data.policy.paused ? "resume" : "pause",
                ),
              )
            }
          >
            {data.policy.paused ? "恢复研究调度" : "暂停研究调度"}
          </button>
        </div>
        <p className="sp-muted">{data.policy.completed ? "项目研究调度已结束，可查看已有结果。" : data.policy.paused ? "后续研究调度已暂停，当前任务仍可保存结果。" : data.policy.auto_research ? "按当前选购目标，在满足条件后自动安排批次研究；开启不代表此刻正在分析。" : "自动研究未开启，可手动发起研究，或在下方设置中授权自动批次研究。"}</p>
        <p className="sp-research-progress" role="status">{execution.label} · 已逐项分析 {data.coverage.evaluated ?? "—"} 件 · 待逐项研究 {data.research_work?.unassessed ?? data.coverage.waiting ?? "—"} 件</p>
        <details className="ua-research-scheduling"><summary>研究状态、覆盖与自动研究设置</summary><AgentResearchStatus data={data} showSchedule={false} /><ReportScopeSummary data={data} research /></details>
        <p className="sp-muted" title="监控独立继续；恢复调度不会开启未授权的自动研究。">暂停仅影响后续研究，当前任务仍会保存结果。</p>
        <button
          disabled={busy || !data.total || goalUnavailable || !!data.policy.paused || !!data.policy.completed}
          onClick={() => action(() => projectApi.study(data.project.id))}
        >
          研究下一个有限批次
        </button>
      </Panel>
      <div className="sp-research-commands" aria-label="研究操作"><button onClick={() => agent.open({ ...defaultAgentScope(data, "research"), question: "深入调查这些商品，请重点核实：" })}>深入调查</button><button onClick={() => { const details = document.querySelector<HTMLDetailsElement>(".sp-research-coverage"); if (details) { const parent=details.closest<HTMLDetailsElement>('.ua-research-scheduling');if(parent)parent.open=true;details.open = true; details.scrollIntoView({ block: "center" }); } }}>查看研究覆盖</button></div>
      <details id="research-investigations" className="ua-investigations sp-research-secondary"><summary>补充取证与调查建议</summary><Investigations id={data.project.id} select={select} /></details>
      <details className="sp-secondary-details sp-research-secondary"><summary>商品证据变化</summary><EvidenceChanges data={data} /></details>
      {data.goal_context ? <ReportHistory data={data} /> : null}
      <h2>研究执行历史</h2>
      <div className="sp-history-filters" role="group" aria-label="研究来源"><span>筛选研究记录</span>{[['all','全部任务'],['user','用户发起'],['automatic','Agent 自主研究']].map(([key,label])=><button key={key} aria-pressed={origin===key} onClick={()=>setOrigin(key)}>{label}</button>)}</div>
      {data.studies.length>0&&origin!=='all'&&!data.studies.some(s=>researchOrigin(s)===(origin==='user'?'用户发起':'Agent 自主研究'))?<p className="sp-muted" role="status">暂无此来源的研究任务；普通问答请在统一 Agent 中查看。</p>:null}
      {data.studies.length ? (
        data.studies.filter(study=>origin==='all'||origin==='user'&&researchOrigin(study)==='用户发起'||origin==='automatic'&&researchOrigin(study)==='Agent 自主研究').map((study) => (
          <Panel key={study.id} className="sp-research-history-card">
            <span id={`research-run-${study.id}`} className="sp-research-run-anchor" />
            <div className="sp-between">
              <h3>
                研究 #{study.id} ·{" "}
                {study.kind === "visual" ? "图片观察（辅助证据）" : study.kind === "reassessment" ? "新证据有限复评" : study.kind === "integration" ? "重要变化整合报告" : study.kind === "followup" ? "有限逐项补研" : study.origin === "automatic_calibration" ? "目标校准" : study.kind === "initial"
                  ? "首轮"
                  : study.kind === "selected"
                    ? "指定范围"
                    : study.kind.startsWith("seller:")
                      ? "卖家公开信息研究"
                      : "增量研究"}
              </h3>
              <StatusBadge status={studyStatus(study)} live={["running", "queued"].includes(study.state)} />
            </div>
            <p className="sp-muted">{researchOrigin(study)} · {date(study.finished_at ?? study.created_at)} · {study.listing_ids.length} 件{study.goal_revision !== data.goal_context?.current_revision ? " · 历史目标" : ""}</p>
            {study.result ? <p className="sp-report-content">{researchConclusion(study.result.content).slice(0, 180)}{researchConclusion(study.result.content).length > 180 ? "…" : ""}</p> : null}
            <details className="sp-research-task-details"><summary>任务详情与证据</summary>
            {researchPurpose(study)?<details><summary>研究重点</summary><p>{researchPurpose(study)}</p></details>:null}
            <p>
              {data.goal_context ? `目标 ${study.goal_revision ? `v${study.goal_revision}` : "版本未核验"}${study.goal_revision !== data.goal_context.current_revision ? "（历史目标，不覆盖当前结论）" : ""} · ` : ""}固定快照 {date(study.snapshot_at)} · {study.kind === "visual" ? "单商品图片辅助证据，不计逐项研究覆盖" : `${study.listing_ids.length} 件 · 商品 ${study.listing_ids.map((id) => `#${id}`).join("、")}`}
            </p>
            {study.goal_text ? <details><summary>启动时的目标</summary><p>{study.goal_text}</p></details> : null}
            {study.kind === "visual" ? <VisualEvidence taskId={data.project.id} studyId={study.id} onQuestion={agent.data?o=>agent.open(visualQuestionScope(o)):undefined} /> : null}
            {study.result ? <button onClick={()=>agent.open({role:'interpret',ids:study.listing_ids,studyId:study.id,label:`研究 #${study.id} 的商品与证据`,question:'请解释这次研究的主要结论和未解决的问题。'})}>追问这次研究</button> : null}
            {study.finished_at ? <p className="sp-status-time">本次结束 {date(study.finished_at)}</p> : null}
            {study.kind === "followup" ? <p className="sp-status-time">补研结果保存在本次记录并计入有效覆盖；不将有限补研小结替换为全项目综合报告。同目标同证据不自动重复尝试。</p> : null}
            {study.error ? <><p className={study.state === "superseded" ? "sp-muted" : "sp-error"}>{study.state==='superseded'?'此任务已不适用于当前目标。':'本次研究未完成，已有证据仍保留。'}</p><details><summary>失败原因</summary><p>{study.error}</p></details></> : null}
            {study.state === "failed" && study.kind !== "visual" ? (
              <button
                disabled={busy || !!data.policy.paused || study.goal_revision!==data.goal_context?.current_revision}
                onClick={() =>
                  action(() => projectApi.retry(data.project.id, study.id))
                }
              >
                重试原快照
              </button>
            ) : null}
            {study.result ? (
              <details>
                <summary>研究结论与依据</summary>
                <p className="sp-report-content">{study.result.content}</p>
                <p className="sp-muted">以下为本次固定快照的原始判断；是否仍适用请核对目标与商品证据版本。</p>
                {study.result.research?.assessments.map(item => <div key={item.listing_id}><strong>商品 #{item.listing_id}</strong><ConditionJudgments assessment={item} criteria={study.result!.research!.criteria} /></div>)}
                {study.kind!=="visual"?study.result.research?.assessments.filter(item=>item.judgments.some(j=>j.evidence_refs.some(ref=>ref.startsWith("visual:")))).map(item=><details key={`visual-${item.listing_id}`}><summary>商品 #{item.listing_id} 的视觉引用依据</summary><VisualEvidence taskId={data.project.id} listingId={item.listing_id} referencedByStudy={study.id} onQuestion={agent.data?o=>agent.open(visualQuestionScope(o)):undefined}/></details>):null}
              </details>
            ) : null}
            </details>
          </Panel>
        ))
      ) : (
        <Panel>
          <p>尚无研究执行。先积累样本，或主动开始有限样本研究。</p>
        </Panel>
      )}
    </>
  );
}
