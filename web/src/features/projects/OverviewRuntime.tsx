import { useGoalContinuity } from "./GoalContinuity";
import { useQuery } from "@tanstack/react-query";
import { monitorApi } from "../../api/monitorClient";
import type { ProjectOverview } from "../../api/projectClient";
import { StatusBadge, StatusSnapshot, useExecutionStatus } from "../../components/status/ExecutionStatus";
import { projectMonitorExecution, researchExecution, researchScheduling } from "../../components/status/statusModel";

function count(value: number) { return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("zh-CN") : "—"; }
export function OverviewRuntime({ data, go }: { data: ProjectOverview; go: (view: string) => void }) {
  const monitors = useQuery({ queryKey: ["monitors", data.project.id], queryFn: () => monitorApi.list(data.project.id), refetchInterval: 3000 });
  const unlinked = useGoalContinuity().state === "unlinked";
  const agent = useExecutionStatus(researchExecution(data));
  const schedule = useExecutionStatus(researchScheduling(data));
  return <section className="sp-overview-runtime" aria-label="项目运行概况">
    <div className="sp-runtime-items">
      <div><button className="sp-runtime-label" onClick={() => go("monitors")}>监控采集 ↗</button>
        <StatusSnapshot observedAt={monitors.dataUpdatedAt} unavailable={monitors.isError || monitors.failureCount > 0 || monitors.fetchStatus === "paused"}>
          <StatusBadge status={projectMonitorExecution(monitors.data)} live />
        </StatusSnapshot>
        {monitors.isError ? <button className="sp-status-link" onClick={() => void monitors.refetch()}>重试状态</button> : null}
      </div>
      <div><span className="sp-runtime-label">全项目商品</span><span><strong>{count(data.total)}</strong> 件去重商品</span></div>
      <div><button className="sp-runtime-label" onClick={() => go("research")}>Agent 研究 ↗</button><StatusBadge status={agent} />
        <small title={schedule.reason}>{schedule.label}</small></div>
      <div><span className="sp-runtime-label">{data.goal_context ? `当前目标 v${data.goal_context.current_revision} 研究覆盖` : unlinked ? "历史证据研究覆盖" : "当前商品版本研究覆盖"}</span><span><strong>{count(data.coverage.evaluated)}</strong> 件已逐项分析</span>
        <small>{data.coverage_history ? `历史逐项分析 ${data.coverage_history.evaluated} 件 · ` : ""}{count(data.coverage.summarized)} 件仅批次概述 · {count(data.coverage.waiting)} 件待研究</small></div>
    </div>
    <p className="sp-runtime-note">{unlinked ? "当前目标下已评估数量暂不可确认。" : ""}运行状态按后端快照更新；规则初筛排除不计入 AI 分析。<button onClick={() => go("research")}>查看覆盖与研究状态 →</button></p>
  </section>;
}
