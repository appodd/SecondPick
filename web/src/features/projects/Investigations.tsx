import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { investigationApi, type Investigations as InvestigationData } from "../../api/investigationClient";
import { browserApi, type BrowserJob } from "../../api/browserClient";
import { request } from "../../api/client";
import { CollectionAudit } from "../conversation/CollectionAudit";
import "./investigations.css";

export const investigationLabels: Record<string, string> = {
  pending: "等待确认", approved: "已批准，尚未执行", queued: "执行已受理，尚未开始", running: "执行中",
  new_evidence: "已获得新证据", no_new_evidence: "已执行，无新增证据", needs_attention: "需要人工处理",
  failed: "执行失败", interrupted: "服务重启，执行中断", cancelled: "已取消", manual: "需要询问卖家或人工核实", unsupported: "卖家公开资料调查暂不支持执行",
};
function ExecutionAudit({ job }: { job: number }) {
  const data = useQuery({ queryKey: ["investigation-browser-job", job], queryFn: () => request<BrowserJob>(`/api/browser/jobs/${job}`),
    refetchInterval: q => !q.state.data || ["queued", "running"].includes(q.state.data.state) ? 2000 : false });
  return data.data ? <CollectionAudit job={data.data} /> : null;
}
export function Investigations({ id, listing, select }: { id: number; listing?: number; select?: (listing: number) => void }) {
  const cache = useQueryClient();
  const queryKey = ["investigations", id, listing ?? "all"];
  const query = useQuery({ queryKey, queryFn: () => investigationApi.list(id, listing), refetchInterval: 3000 });
  const [pending, setPending] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [skipped, setSkipped] = useState<InvestigationData["skipped"]>([]);
  useEffect(() => { setSkipped([]); setError(""); setNotice(""); }, [id]);
  async function run(action: () => Promise<InvestigationData | unknown>) {
    if (pending) return;
    setPending(true); setError(""); setNotice("");
    try {
      const value = await action();
      if (value && typeof value === "object" && "items" in value) {
        cache.setQueryData(queryKey, value);
        const decisions = (value as InvestigationData).skipped;
        if (decisions?.length) setSkipped(decisions);
      }
      await query.refetch();
      void cache.invalidateQueries({ queryKey: ["project", id, "evidence"] });
      setNotice("已更新调查记录；后续复评以研究队列实际状态为准。");
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setPending(false); }
  }
  const items = (query.data?.items ?? []).filter(item => listing === undefined || item.listing_id === listing);
  const terminalKey = items.filter(i => i.job_id && !["queued", "running"].includes(i.job_state ?? "")).map(i => `${i.id}:${i.state}`).join(",");
  useEffect(() => { if (terminalKey) void cache.invalidateQueries({ queryKey: ["project", id] }); }, [terminalKey, id, cache]);
  return <section className="sp-investigations sp-panel" id={listing ? `listing-investigations-${listing}` : "project-investigations"} aria-label="调查建议与执行">
    <div className="sp-between"><h2>{listing ? "本商品调查与证据缺口" : "调查建议与执行"}</h2><button disabled={pending || query.isPending} onClick={() => void run(() => investigationApi.plan(id, listing ? [listing] : undefined))}>{pending ? "提交中…" : listing ? "整理本商品调查" : "整理已有研究的调查建议"}</button></div>
    <p className="sp-muted">整理建议复用已保存研究，不调用 AI；最多 3 件待处理商品。每次额外详情访问须单独批准，不访问卖家主页或联系卖家；后续复评遵守研究授权与暂停设置。</p>
    {query.data?.automatic_research_held ? <p role="status">调查尚未执行完毕：暂不自动安排本项目模型任务，授权与暂停设置保持不变。</p> : null}
    {query.isPending ? <p>加载调查记录…</p> : null}
    {query.error ? <p role="alert">调查记录加载失败。<button onClick={() => void query.refetch()}>重试</button></p> : null}
    {error ? <p role="alert">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
    {!query.isPending && !items.length ? <p>暂无调查建议。可按已有提名、收藏和证据缺口整理，无需逐件编写问题。</p> : null}
    {items.map(item => <article key={item.id} className="sp-investigation-row" aria-label={`商品 #${item.listing_id} 调查`}>
      <div className="sp-between"><strong>#{item.listing_id} · {item.plan.title}</strong><span role="status">{investigationLabels[item.state] ?? "状态待确认"}</span></div>
      <p>{item.plan.objective} · 目标 v{item.goal_revision}</p><p>{item.plan.reason}</p>
      {item.outdated ? <p>目标已变化，此计划不能再执行；请取消后重新整理。</p> : null}
      <p className="sp-muted">{item.plan.capability}。{item.plan.expected_information.join("、") || "目前没有可通过详情访问补充的字段"}</p>
      {item.plan.manual_questions.length ? <details><summary>需询问卖家或人工核实（不会自动联系）</summary><ul>{item.plan.manual_questions.map((q, n) => <li key={n}>{q}</li>)}</ul></details> : null}
      {item.plan.seller_public_questions.length ? <details><summary>卖家公开资料需求（当前不支持执行）</summary><ul>{item.plan.seller_public_questions.map((q, n) => <li key={n}>{q}</li>)}</ul></details> : null}
      {item.error_code ? <p>执行原因：{item.error_code}。不会自动重试或抢占其他任务。</p> : null}
      {item.outcome.new_evidence ? <p>新证据已保存{item.outcome.detail_snapshot_ids?.length ? `（详情记录 ${item.outcome.detail_snapshot_ids.map(i => `#${i}`).join("、")}）` : ""}。{item.outcome.reassessed ? "已按新证据完成逐项复评；综合报告整合状态见研究概览" : item.outcome.manually_reassessed ? "已有后续手动逐项研究" : "待重新评估；原报告和历史判断尚未按新证据更新"}。</p> : null}
      <div className="sp-actions">
        {select ? <button onClick={() => select(item.listing_id)}>查看商品证据</button> : null}
        {item.kind === "detail" && item.state === "pending" ? <button disabled={pending || item.outdated} onClick={() => void run(() => investigationApi.act(id,item.id,"approve"))}>批准本商品一次详情访问</button> : null}
        {item.state === "approved" ? <button disabled={pending || item.outdated} onClick={() => void run(() => investigationApi.act(id,item.id,"execute"))}>确认执行（仅 1 件详情）</button> : null}
        {!item.job_id && item.state !== "cancelled" ? <button disabled={pending} onClick={() => void run(() => investigationApi.act(id,item.id,"cancel"))}>{item.state === "approved" ? "取消未执行调查" : "跳过"}</button> : null}
        {item.job_id && ["queued","running","needs_attention"].includes(item.state) && ["queued","running"].includes(item.job_state ?? "") ? <button disabled={pending} onClick={() => void run(() => browserApi.cancel(item.job_id!))}>取消执行</button> : null}
        {item.job_id && item.stage === "waiting_verification" && item.job_state === "running" ? <button disabled={pending} onClick={() => void run(() => browserApi.resumeVerification(item.job_id!))}>已在浏览器完成验证，继续</button> : null}
      </div>
      {item.job_id ? <ExecutionAudit job={item.job_id} /> : null}
      <small>调查 #{item.id}{item.job_id ? ` · BrowserJob #${item.job_id}` : ""} · 来源研究 {item.plan.source_study_ids.map(i => `#${i}`).join("、") || "用户指定 / 收藏"}</small>
    </article>)}
    {skipped.length ? <details><summary>未选入原因</summary><ul>{skipped.map(item => <li key={item.listing_id}>#{item.listing_id}：{item.reason}</li>)}</ul></details> : null}
  </section>;
}
