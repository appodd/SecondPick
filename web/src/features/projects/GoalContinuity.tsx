import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { TaskDetail } from "../../api/types";
import { projectApi, type ProjectOverview } from "../../api/projectClient";
import { StatusBadge } from "../../components/status/ExecutionStatus";
import { Modal, price } from "./projectUi";
import { goalRecordState, impactSummary, initialGoalProposal, memoryMinimum, supportsMemory, type GoalProposal } from "./goalImpact";
import "./goal-continuity.css";
import { GoalMonitorReview } from './GoalMonitorReview';
import { Sparkles } from 'lucide-react';
import { GoalChanges } from './GoalChanges';
import { preserveConditionWording } from './goalConditionComparison';

export function calibrationLabel(context: NonNullable<ProjectOverview["goal_context"]>) {
  if (context.calibration === "current") return `目标 v${context.current_revision} 的研究结论已就绪`;
  if (context.calibration === "running") return `正在按目标 v${context.current_revision} 研究`;
  if (context.calibration_work?.state === "scheduled") return `目标 v${context.current_revision} 校准研究已安排`;
  if (context.calibration_work?.state === "unavailable") return `目标 v${context.current_revision} 结论待校准 · 无法自动研究`;
  if (context.calibration_work?.state === "not_needed") return `目标 v${context.current_revision} 已生效 · 暂不自动重研`;
  return context.current_revision>1 ? `新目标 v${context.current_revision} 已生效，研究结论待校准` : "历史报告目标版本未核验，研究结论待校准";
}

interface GoalContext { state: "unknown" | "unlinked" | "unversioned"; detail?: TaskDetail; loading: boolean; retry: () => void }
const Context = createContext<GoalContext>({ state: "unknown", loading: false, retry: () => {} });
export const useGoalContinuity = () => useContext(Context);
export function GoalContinuityProvider({ data, children, unavailable: sourceUnavailable = false }: { data?: ProjectOverview; children: ReactNode; unavailable?: boolean }) {
  const id = data?.project.id;
  const query = useQuery({ queryKey: ["task", id], queryFn: () => api.getTask(id!), enabled: id !== undefined && (!data?.goal_context || data.goal_context.legacy_unmerged), refetchInterval: 5000 });
  const unavailable = sourceUnavailable || !data?.goal_context && (query.isError || query.failureCount > 0 || query.fetchStatus === "paused");
  return <Context.Provider value={{ state: data ? goalRecordState(data, query.data, unavailable) : "unknown", detail: unavailable ? undefined : query.data, loading: !data?.goal_context && query.isPending && !unavailable, retry: () => void query.refetch() }}>{children}</Context.Provider>;
}
export function GoalContinuityNotice({ data }: { data?: ProjectOverview }) {
  const goal = useGoalContinuity();
  if (goal.loading) return null;
  const context = data?.goal_context;
  if (goal.state === "unversioned" && context && (context.current_revision>1 || data?.report && !context.report_current)) {
    const failed = !context.report_current && data?.studies.some(study => study.id === context.calibration_work?.study_id && study.state === "failed");
    const label = failed ? `目标 v${context.current_revision} 校准研究失败 · 结论待更新` : data?.policy && !data.policy.auto_research && !context.report_current ? `目标 v${context.current_revision} 已生效 · ${data?.report?'综合报告待更新':'尚无综合报告'}` : calibrationLabel(context);
    return <aside className="sp-goal-notice" aria-label="研究目标衔接提示"><StatusBadge status={{ kind: failed ? "attention" : context.calibration === "current" ? "success" : context.calibration === "running" ? "running" : "waiting", label }} />
      <p>{context.report_current ? "当前结论绑定此目标版本，历史报告与收藏仍保留。" : data?.report ? "旧报告和候选仅作历史参考，当前目标的综合报告尚待更新。" : "新条件已生效，尚无当前目标的综合报告；本次研究答复可单独查看。"}</p>
      {context.calibration === "pending" && data?.report ? <p>按保存记录，原报告 {impactSummary(data,initialGoalProposal(data)).candidates.length} 件候选中，有 {impactSummary(data,initialGoalProposal(data)).candidates.filter(item => item.kind === "outside").length} 件需按新条件复核。配置自述尚未独立核验，收藏继续保留。</p> : null}
      {context.calibration_work ? <p>{context.calibration_work.reason}{context.calibration_work.study_id ? <Link to={`/projects/${data.project.id}?view=research#research-run-${context.calibration_work.study_id}`}> 查看校准研究 →</Link> : null}</p> : context.calibration === "pending" ? <p>当前服务未提供自动校准状态，可在 Agent 研究页手动研究有限样本。监控保持原配置。</p> : null}</aside>;
  }
  if (goal.state === "unversioned") return null;
  return <aside className="sp-goal-notice" aria-label="研究目标衔接提示">
    <StatusBadge status={{ kind: goal.state === "unknown" ? "unknown" : "waiting", label: goal.state === "unlinked" ? "选购条件记录未衔接 · 结论待校准" : "目标版本暂不可确认" }} />
    <p>{goal.state === "unlinked" ? "旧版对话已有偏好修订或目标记录不同，但项目研究仍读取原始目标和独立硬条件。已有报告与候选仅作历史参考，不能确认已按新条件评估；当前运行任务也不能据此视为正在校准新目标。" : "当前无法核对目标记录；保留已保存的研究内容，不将其标记为已按最新条件校准。"}</p>
    {goal.state === "unknown" ? <button onClick={goal.retry}>重新核对目标记录</button> : null}
  </aside>;
}

/** Confirmed goal updates use the versioned endpoint; previews remain local and free of AI calls. */
export function GoalAdjustment({ data, hideTrigger = false }: { data: ProjectOverview; hideTrigger?: boolean }) {
  const [route, setRoute] = useSearchParams();
  const [open, setOpen] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  function close() {
    setOpen(false);
    if (route.has("editGoal")) { const next = new URLSearchParams(route); next.delete("editGoal"); next.delete('goalRequest');setRoute(next, { replace: true }); }
    requestAnimationFrame(() => { if (!document.querySelector('[role="dialog"]')) launcher.current?.focus(); });
  }
  function createProject(){setOpen(false);const next=new URLSearchParams(route);next.delete('editGoal');next.delete('goalRequest');next.set('create','1');setRoute(next)}
  return <>{!hideTrigger ? <button ref={launcher} onClick={() => setOpen(true)}>调整选购条件</button> : null}{open || route.get("editGoal") === "1" ? <GoalPreview key={data.project.id} data={data} close={close} createProject={createProject} instruction={route.get('goalRequest')??undefined} /> : null}</>;
}
function GoalPreview({ data, close, createProject, instruction }: { data: ProjectOverview; close: () => void; createProject:()=>void; instruction?:string }) {
  const memoryApplicable = supportsMemory(data);
  const [draft, setDraft] = useState(() => ({ ...initialGoalProposal(data), minimumMemory: memoryApplicable ? initialGoalProposal(data).minimumMemory : null }));
  const [baseRevision] = useState(data.goal_context?.current_revision);
  const [before] = useState(()=>initialGoalProposal(data));
  const [intent,setIntent]=useState(instruction??'');
  const [appliedIntent,setAppliedIntent]=useState<string|null>(null);
  const [draftReady,setDraftReady]=useState(false),[manual,setManual]=useState(false);
  const draftRef=useRef<HTMLElement>(null),impactRef=useRef<HTMLElement>(null);
  function reveal(ref:typeof draftRef){requestAnimationFrame(()=>ref.current?.scrollIntoView?.({block:'start',behavior:'smooth'}))}
  const [saving, setSaving] = useState(false), [saved, setSaved] = useState<number>(), [error, setError] = useState("");
  const mounted=useRef(true),latestData=useRef(data);
  latestData.current=data;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
  const [suggestionNote,setSuggestionNote]=useState('');
  const [suggesting,setSuggesting]=useState(false),suggestionBusy=useRef(false);
  async function suggest(){
    if(suggestionBusy.current||saving||saved||!intent.trim()||changedElsewhere)return;
    const requested=intent.trim();
    suggestionBusy.current=true;setSuggesting(true);setError('');setSuggestionNote('正在整理预算、必须条件和偏好，尚未保存。');setPreview(false);
    try{
      const result=await projectApi.draft(requested,canonicalPayload);
      if(!mounted.current)return;
      if(latestData.current.goal_context?.current_revision!==baseRevision){setSuggestionNote('项目目标已在其他位置更新，本次草案未填入。请关闭后重新打开。');return}
      const parsed=initialGoalProposal({...data,project:{...data.project,goal:result.goal},policy:{...data.policy,budget:result.budget,hard:preserveConditionWording(result.hard,canonicalPayload.hard),soft:preserveConditionWording(result.soft,canonicalPayload.soft)}});
      setDraft({...parsed,minimumMemory:memoryApplicable?parsed.minimumMemory:null});
      setDraftReady(true);setAppliedIntent(requested);
      reveal(draftRef);
      setSuggestionNote('已整理修改草案，请核对变化与保留条件，再预览影响并确认保存。');
    }catch(e){if(mounted.current){setSuggestionNote('');setError(`AI 整理未完成：${e instanceof Error?e.message:String(e)}。已保留原表单，可重试或手动修改。`)}}
    finally{suggestionBusy.current=false;if(mounted.current)setSuggesting(false)}
  }
  const pending = useRef(false), request = useRef({ signature: "", key: "" });
  const cache = useQueryClient();
  async function save() {
    if (pending.current || !draftReady || unappliedIntent || !preview || !baseRevision || changedElsewhere && !retryable || invalid || saved) return;
    const payload = canonicalPayload;
    const signature = JSON.stringify([baseRevision,payload]);
    if (signature !== request.current.signature) request.current = { signature, key: crypto.randomUUID() };
    pending.current = true; setSaving(true); setError("");
    try {
      const result = await projectApi.saveGoal(data.project.id,payload,baseRevision,request.current.key);
      setSaved(result.revision);
      await cache.invalidateQueries({ queryKey: ["project",data.project.id] });
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { pending.current = false; setSaving(false); }
  }
  const [base] = useState(() => JSON.stringify(initialGoalProposal(data)));
  const [preview, setPreview] = useState(false);
  const goal = useGoalContinuity();
  const changedElsewhere = !saved && (base !== JSON.stringify(initialGoalProposal(data)) || baseRevision !== data.goal_context?.current_revision);
  const impact = useMemo(() => impactSummary(data, draft), [data.cards, data.report, draft]);
  const invalid = !draft.goal.trim() || draft.budget !== null && (!Number.isFinite(draft.budget) || draft.budget < 0)
    || draft.minimumMemory !== null && (!Number.isSafeInteger(draft.minimumMemory) || draft.minimumMemory <= 0);
  function edit<K extends keyof GoalProposal>(key: K, value: GoalProposal[K]) {
    setDraft(current => {
      const next={...current,[key]:value};
      if(key==='minimumMemory')next.hard=current.hard.filter(s=>memoryMinimum(s)===null);
      if(key==='hard'){const values=(value as string[]).map(memoryMinimum).filter((v):v is number=>v!==null);next.minimumMemory=values.length?Math.max(...values):null}
      return next;
    });setPreview(false);setSuggestionNote('');
  }
  const canonicalPayload = { goal: draft.goal.trim(), budget: draft.budget,
    hard: [...new Set([...draft.hard.map(s => s.trim()).filter(Boolean), ...(memoryApplicable && draft.minimumMemory ? [`内存至少${draft.minimumMemory}GB`] : [])])],
    soft: draft.soft.map(s => s.trim()).filter(Boolean) };
  const retryable = !!error && request.current.signature === JSON.stringify([baseRevision,canonicalPayload]);
  const unappliedIntent=!!intent.trim() && appliedIntent!==intent.trim();
  const dirty=!!intent.trim() || draftReady;
  function requestClose(){if(saving)return;if(!saved&&dirty&&!window.confirm('放弃本次未保存的修改草案？'))return;close()}
  function newProject(){if(saving||suggesting)return;if(!saved&&dirty&&!window.confirm('新建选购项目会放弃本次未保存的修改草案，是否继续？'))return;createProject()}
  function openManual(){setDraftReady(true);setManual(value=>!value);reveal(draftRef)}
  function previewImpact(){setPreview(true);reveal(impactRef)}
  const names = { outside: "按记录不满足", unknown: "信息待核实", meets_known: "已知条件暂符合" };
  function rows(items: typeof impact.items) {
    return <ul className="sp-goal-impact-list">{items.slice(0, 40).map(item => <li key={item.card.listing_id}>
      <div><strong>#{item.card.listing_id} · {item.card.title}</strong><b>{price(item.card)}</b></div>
      <StatusBadge status={{ kind: "waiting", label: names[item.kind] }} />
      <ul>{item.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
    </li>)}</ul>;
  }
  const footer=<><div className="sp-goal-fixed-actions"><button disabled={saving} onClick={requestClose}>{saved?'完成':'取消'}</button>{!saved ? <button className="sp-primary" disabled={!draftReady || unappliedIntent || invalid || changedElsewhere && !retryable || saving || suggesting || !baseRevision} onClick={()=>preview?void save():previewImpact()}>{saving?'正在保存…':preview?'确认并保存修改':'预览调整影响'}</button> : null}</div><p className="sp-muted sp-goal-footer-note">{saved?'已保存。现有商品、历史研究和监控配置保留。':unappliedIntent&&draftReady?'修改意图已变化，请重新整理草案后再预览。':preview?'请核对影响。确认保存后，项目目标才会更新。':draftReady?'草案尚未生效，请预览影响后确认保存。':'描述修改意图，或直接手动修改；尚未更改项目目标。'}</p></>;
  return <div className="sp-goal-preview"><Modal title="调整选购条件" close={requestClose} footer={footer}>
    <StatusBadge status={{ kind: saved ? "success" : "waiting", label: saved ? saved===baseRevision ? `目标 v${saved} 已确认，版本未变化` : `已从 v${baseRevision} 更新为 v${saved}` : "本次拟修改 · 尚未保存" }} />
    {saved ? <p>新条件已保存，研究报告是否已校准以下方项目状态为准；不会自动修改监控或清空历史。</p> : null}
    {saved ? <><h3>检查新目标的监控范围</h3><GoalMonitorReview id={data.project.id} goal={(data.goal_context?.current_revision ?? 0)>saved ? data.project.goal : canonicalPayload.goal} hard={(data.goal_context?.current_revision ?? 0)>saved ? data.policy.hard : canonicalPayload.hard}/></> : null}
    {saved && (data.goal_context?.current_revision ?? saved) > saved ? <p>本次保存的是 v{saved}，项目已更新到 v{data.goal_context?.current_revision}，请以当前版本为准。</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {goal.state === "unlinked" ? <p className="sp-goal-notice">旧版对话记录：{goal.detail?.task.effective_goal ?? "条件文本尚未读到，请先核对已有条件"}。下方基于项目研究当前采用的条件准备草案，尚未合并两条记录。</p> : null}
    <section className="sp-goal-before" aria-label="修改前的已保存目标"><h3>{saved||changedElsewhere?'调整前目标':'当前生效目标'}{baseRevision ? ` v${baseRevision}` : ''}</h3><p>{before.goal}</p><p className="sp-goal-current-meta">预算：{before.budget===null?'未设置':`¥${before.budget.toLocaleString()}`}</p><details><summary>查看完整条件</summary><dl><div><dt>必须条件</dt><dd>{before.hard.join('；')||'未单独设置'}</dd></div><div><dt>个人偏好</dt><dd>{before.soft.join('；')||'未单独设置'}</dd></div></dl><small>最初目标及历次修改可在研究概览的“查看历史目标”中查看。</small></details></section>
    {changedElsewhere ? <p role={retryable || saving ? "status" : "alert"}>{saving ? "服务器记录已变化，正在核对本次保存响应…" : retryable ? "服务器目标已变化，可重试核对这次提交的结果；不会覆盖更新的版本。" : "项目条件已发生变化，请关闭后重新打开预览；你的草案没有覆盖服务器记录。"}</p> : null}
    <section className="sp-goal-intent"><h3><span className="sp-goal-step">1</span>描述想做的修改</h3>
    <label>修改意图<textarea aria-label="修改意图" rows={4} maxLength={8000} placeholder="例如：最低芯片改为 M3，预算提高到 6000 元，其他条件保持不变。" disabled={saving||suggesting||!!saved} value={intent} onChange={event=>{setIntent(event.target.value);setPreview(false);setSuggestionNote('')}}/></label>
    <p className="sp-goal-new-project-hint">如果改买另一类商品，或想保留两套目标分别比较，建议新建项目。<button disabled={saving||suggesting} onClick={newProject}>新建选购项目 →</button></p>
    <div className="sp-actions sp-goal-ai-actions"><button disabled={!intent.trim()||changedElsewhere||saving||suggesting||!!saved} onClick={()=>void suggest()}><Sparkles size={15} aria-hidden="true"/>{suggesting?'AI 正在整理…':draftReady?'重新整理修改方案':'AI 整理修改方案'}</button>{!draftReady ? <button disabled={saving||suggesting||!!saved} onClick={openManual}>直接手动修改</button> : null}</div>
    <p className="sp-muted">结合当前目标生成可编辑草案，不会直接保存、启动研究或修改监控。</p>
    {suggestionNote ? <p role="status">{suggestionNote}</p> : null}
    </section>
    {draftReady ? <section ref={draftRef} className="sp-goal-draft" aria-label="修改草案"><h3><span className="sp-goal-step">2</span>检查修改草案</h3><p className="sp-goal-draft-goal">{draft.goal}</p>
    <GoalChanges before={before} after={canonicalPayload} saved={!!saved} showRetained/>
    {unappliedIntent ? <p className="sp-goal-stale" role="status">修改意图尚未应用到草案，请重新整理，或清空修改意图后仅使用手动草案。</p> : null}
    <button className="sp-goal-edit-toggle" aria-expanded={manual} onClick={()=>setManual(!manual)}>{manual?'收起编辑字段':'展开编辑字段'}</button>
    {manual ? <fieldset disabled={saving || suggesting || !!saved}><label>调整后的选购目标<textarea aria-label="调整后的选购目标" rows={4} maxLength={8000} value={draft.goal} onChange={event=>edit('goal',event.target.value)}/></label>
    <div className="sp-goal-fields"><label>拟定预算上限（元）<input aria-label="拟定预算上限（元）" type="number" min={0} value={draft.budget ?? ""} onChange={event => edit("budget", event.target.value === "" ? null : Number(event.target.value))} /></label>
      {memoryApplicable ? <label>拟定最低内存（GB）<input aria-label="拟定最低内存（GB）" type="number" min={1} step={1} value={draft.minimumMemory ?? ""} onChange={event => edit("minimumMemory", event.target.value === "" ? null : Number(event.target.value))} /></label> : null}</div>
    <label>保留的硬条件（每行一项）<textarea aria-label="保留的硬条件（每行一项）" rows={4} value={draft.hard.join("\n")} onChange={event => edit("hard", event.target.value.split("\n"))} /></label>
    <label>软偏好（每行一项）<textarea aria-label="软偏好（每行一项）" rows={2} value={draft.soft.join("\n")} onChange={event => edit("soft", event.target.value.split("\n"))} /></label>
    <details className="sp-goal-field-help"><summary>地区条件说明</summary><p>地区默认不设偏好。「上海优先」填入软偏好，「只考虑上海自提」填入必须条件；保存目标不会自动修改监控。</p>{data.region_preference?.legacy_unverified ? <p>历史城市记录为「{data.region_preference.legacy_city}」，来源无法确认，不会自动作为地区偏好；如有要求，请明确填写。</p> : null}</details>
    <p className="sp-muted">目标原文不自动变成硬条件。明确的预算和能用现有字段核对的条件参与预览；其他硬条件保留待核实，软偏好不作排除依据。扩展配置只在品类和已有字段适用时显示。</p>
    </fieldset> : null}</section> : null}
    {invalid ? <p role="alert">请填写目标，预算须为非负数，最低内存须为正整数。</p> : null}
    {preview ? <section ref={impactRef} className="sp-goal-impact" aria-label="目标调整影响预览">
      <h3>调整影响</h3><p>{data.report?'旧报告基于修改前的目标，保存后需重新核对。':'保存后，新研究将按调整后的目标进行。'}已有商品、收藏和研究记录保留，监控范围不会自动修改。</p>
      <details className="sp-goal-impact-details"><summary>展开商品核对详情</summary><p className="sp-muted">仅用已保存的价格、部分配置等字段作规则核对，没有重新筛选或调用 AI 研究商品。</p>
      <h3>原报告候选需要怎样复核？</h3>
      <p>原报告可读取候选 {impact.candidates.length} 件，其中 {impact.candidates.filter(item => item.kind === "outside").length} 件按保存记录不满足拟定条件。原报告、商品和收藏均保留。</p>
      {impact.candidates.length ? rows(impact.candidates) : <p>暂无可读取的报告候选；不据此断言没有合适商品。</p>}
      <h3>现有商品低成本核对</h3>
      <div className="sp-goal-counts">{Object.entries(impact.counts).map(([key, count]) => <div key={key}><b>{count}</b><span>{names[key as keyof typeof names]}</span></div>)}</div>
      <p>共 {impact.items.length} 件去重商品，三类互斥。“暂符合”仅指可核对的字段，不代表通过完整目标或 AI 研究。</p>
      <details><summary>查看商品核对依据</summary>{impact.items.length > 40 ? <p>仅展示前40件依据；上方统计仍覆盖全部{impact.items.length}件。</p> : null}{rows(impact.items)}</details>
      <p className="sp-muted">价格来自当前接口保存的挂牌记录，不是实时价格；内存仅从卖家标题识别，未独立核验。多配置、显存、缺失信息不能当成已确认的系统内存。没有重新抓取或调用模型。</p>
      <h3>目标保存与研究分开进行</h3><p>预览不计入 AI 覆盖。保存后新任务使用新目标版本，旧任务结果保留为历史；不会把旧任务标记为新目标研究。</p>
      <p>保存后可检查现有监控是否覆盖新目标；缺少范围时准备新监控，确认后才启动。商品、收藏、旧目标与历史研究均保留。</p>
      <p>确认后先复用保存证据。{data.goal_context?.automatic_calibration_supported ? "已授权且未暂停时，目标、预算或硬条件变化可自动安排一个有限校准批次；仅软偏好变化暂不自动调用 AI。" : "当前服务未开启自动校准，可手动研究受影响候选与未解决事项。"}授权、暂停与监控配置保留，监控变更另行确认。</p>
      </details>
    </section> : null}
    {!baseRevision ? <p>当前服务未提供目标版本，暂不能提交，请先更新服务并重新读取项目。</p> : null}
  </Modal></div>;
}
