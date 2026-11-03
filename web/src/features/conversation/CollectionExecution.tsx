import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { ActionRequestDto } from "../../api/types";
import { api } from "../../api/client";
import { queries } from "../../api/queries";
import { browserApi, browserStageLabel, browserStatusQuery, isBrowserActive } from "../../api/browserClient";
import { CollectionAudit } from "./CollectionAudit";

export function CollectionExecution({ request }: { request: ActionRequestDto }) {
  const client = useQueryClient();
  const [query, setQuery] = useState(request.search_query ?? "");
  const [pages, setPages] = useState(request.max_pages ?? 1);
  const [acknowledged, setAcknowledged] = useState(false);
  const status = useQuery(browserStatusQuery());
  const effectivePages = Math.min(pages, status.data?.max_pages ?? pages);
  const key = ["collection", request.id];
  const execution = useQuery({ queryKey: key, queryFn: () => browserApi.execution(request.task_id, request.id), refetchInterval: 2000 });
  const job = execution.data;
  const active = isBrowserActive(job);
  const analysis = useQuery(queries.operation(job?.analysis_operation_id ?? undefined));
  const analysisState = analysis.data?.operation.state;
  const analyze = useMutation({ mutationFn: () => api.analyzeCollection(job!.id), onSuccess: result => {
    client.setQueryData(["operation", result.operation.id], result);
    void client.invalidateQueries({ queryKey: key });
    void client.invalidateQueries({ queryKey: ["task", request.task_id, "messages"] });
  } });
  const supported = request.actions.every(action => action === "search" || action === "detail");
  const retry = job && ["failed", "cancelled", "interrupted"].includes(job.state);
  const execute = useMutation({ mutationFn: () => browserApi.execute(request.task_id, request.id, job?.query ?? query, job?.max_pages ?? effectivePages, retry ? job.id : undefined),
    onSuccess: result => { client.setQueryData(key, result); setAcknowledged(false); },
    onSettled: () => client.invalidateQueries({ queryKey: ["browser-status"] }),
  });
  const stop = useMutation({ mutationFn: () => browserApi.cancel(job!.id), onSuccess: result => client.setQueryData(key, result) });
  const resume = useMutation({ mutationFn: () => browserApi.resumeVerification(job!.id), onSuccess: result => client.setQueryData(key, result) });
  useEffect(() => {
    if (job && !isBrowserActive(job)) {
      void client.invalidateQueries({ queryKey: ["task", request.task_id] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["browser-status"] });
    }
  }, [job?.id, job?.state, request.task_id, client]);
  if (!supported) return <p>网页目前支持搜索和商品详情采集。此请求包含尚未接入的图片下载或 OCR，请重新请求仅搜索或详情采集。</p>;
  return <div className="collection-execution">
    {request.actions.includes("search") && <><p className="muted">{request.search_query ? "助手已建议搜索范围，可在执行前调整。" : "填写具体搜索词后执行。"}</p><div className="collection-fields">
      <label>搜索词<input aria-label="搜索词" value={job?.query ?? query} maxLength={120} disabled={!!job || execute.isPending} onChange={event => setQuery(event.target.value)} placeholder="例如：iPhone 15 Pro 256G" /></label>
      <label>最多搜索页数<select aria-label="最多搜索页数" value={job?.max_pages ?? effectivePages} disabled={!!job || execute.isPending} onChange={event => setPages(Number(event.target.value))}>
        {Array.from({ length: Math.max(status.data?.max_pages ?? 1, job?.max_pages ?? 1) }, (_, i) => <option key={i} value={i + 1}>{i + 1} 页</option>)}
      </select></label>
    </div></>}
    {job && <div role="status"><p>{browserStageLabel[job.stage] ?? job.stage} · 已保存 {job.result.listing_count} 条商品记录</p>
      {job.error_detail && <p className="scoped-error">{job.error_detail}</p>}
      {job.state === "completed" && <p>{job.analysis_operation_id ?
        analysisState === "waiting_confirmation" ? "助手已分析采集结果，请查看发现与下一步采集建议。" :
        analysisState === "completed" ? "助手已分析采集结果，结论已保存到对话。" :
        ["failed", "interrupted", "cancelled"].includes(analysisState ?? "") ? "后续分析未完成，可在对话中继续询问已有证据。" :
        "助手正在自动分析采集结果…" : "结果已加入当前任务，可开始分析已有商品。"}</p>}
    </div>}
    {active && job?.stage === "waiting_verification" && <div className="collection-verification">
      <p>请在保留的闲鱼窗口中手动完成安全验证，确认商品详情已显示，再回来继续。窗口最多保留至本次操作超时（10 分钟）。</p>
      <button className="primary-button" disabled={resume.isPending || job.verify_requested || job.stop_requested} onClick={() => resume.mutate()}>
        {resume.isPending || job.verify_requested ? "正在检查…" : "我已完成验证，继续采集"}
      </button>
    </div>}
    {(!job || retry) && <>
      {status.data?.auth_status !== "verified" && <p>执行前需要<Link to="/settings">登录闲鱼并验证</Link>。</p>}
      <label className="collection-ack"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} />我已核对范围，了解访问闲鱼可能触发验证或账号限制</label>
      <button className="primary-button" disabled={!acknowledged || execution.isPending || execution.isError || execute.isPending || !status.data?.enabled || status.data.auth_status !== "verified" || !!status.data.active_job || (request.actions.includes("search") && !(job?.query ?? query).trim())}
        onClick={() => execute.mutate()}>{execute.isPending ? "正在提交…" : retry ? "重试采集" : "执行采集"}</button>
      {status.data?.active_job && <p className="muted">浏览器正忙，请等待当前登录或采集结束。</p>}
    </>}
    {active && <button disabled={stop.isPending || job?.stop_requested} onClick={() => stop.mutate()}>停止采集</button>}
    {job && <CollectionAudit key={job.id} job={job} />}
    {job?.state === "completed" && !job.analysis_operation_id && <button className="primary-button" disabled={analyze.isPending || !!status.data?.active_job} onClick={() => analyze.mutate()}>分析已采集结果</button>}
    {(execution.error || execute.error || stop.error || resume.error || status.error || analyze.error || analysis.error) && <p role="alert" className="scoped-error">{execute.error?.message ?? stop.error?.message ?? resume.error?.message ?? analyze.error?.message ?? analysis.error?.message ?? execution.error?.message ?? status.error?.message}</p>}
  </div>;
}
