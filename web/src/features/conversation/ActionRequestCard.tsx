import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { browserApi, browserStageLabel, isBrowserActive } from "../../api/browserClient";
import { api } from "../../api/client";
import type { ActionRequestDto } from "../../api/types";
import { CollectionExecution } from "./CollectionExecution";

const labels = { search: "搜索", detail: "商品详情", media: "图片采集", ocr: "图片文字识别" };
export function ActionRequestCard({ request }: { request: ActionRequestDto }) {
  const client = useQueryClient();
  const decision = useMutation({
    mutationFn: (value: "approve" | "reject") => api.decideAction(request.task_id, request.id, value),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["task", request.task_id, "action-requests"] });
      void client.invalidateQueries({ queryKey: ["operation", request.operation_id] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const current = decision.data?.action_request ?? request;
  const execution = useQuery({ queryKey: ["collection", request.id], queryFn: () => browserApi.execution(request.task_id, request.id),
    enabled: current.state === "approved", refetchInterval: 2000 });
  const job = execution.data;
  const [expanded, setExpanded] = useState(current.state !== "rejected");
  useEffect(() => {
    if (current.state === "rejected" || (job && !isBrowserActive(job))) setExpanded(false);
    else if (job && isBrowserActive(job)) setExpanded(true);
  }, [current.state, job?.id, job?.state]);
  const status = current.state === "pending" ? "待确认" : current.state === "rejected" ? "已拒绝" :
    job ? `${browserStageLabel[job.stage] ?? job.stage}${job.result.listing_count ? ` · ${job.result.listing_count} 条记录` : ""}` : "待执行";
  return <details className="action-request" aria-label="采集请求" data-request-state={current.state}
    open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary><span>{current.actions.map(action => labels[action]).join("、")}请求</span><span className="action-request__status">{status}</span></summary>
    <div className="action-request__body"><h3>{current.summary}</h3>
    <dl><div><dt>拟执行动作</dt><dd>{current.actions.map(action => labels[action]).join("、")}</dd></div>
      <div><dt>商品范围</dt><dd>{current.listing_ids.length ? `${current.listing_ids.length} 件 · ${current.listing_ids.map(id => `#${id}`).join("、")}` : "新搜索，未指定商品"}</dd></div>
      <div><dt>风险说明</dt><dd>{current.risk}</dd></div></dl>
    <p className="action-request__notice">确认仅记录请求；点击“执行采集”后才访问闲鱼</p>
    {current.state === "pending" ? <div className="action-request__buttons">
      <button className="primary-button" disabled={decision.isPending} onClick={() => decision.mutate("approve")}>确认</button>
      <button disabled={decision.isPending} onClick={() => decision.mutate("reject")}>拒绝</button>
    </div> : <p role="status">{current.state === "approved" ? "已确认，请核对执行范围" : "已拒绝，未执行采集"}</p>}
    {current.state === "approved" && <CollectionExecution request={current} />}
    {decision.error && <p className="scoped-error" role="alert">{decision.error.message}</p>}
    </div>
  </details>;
}
