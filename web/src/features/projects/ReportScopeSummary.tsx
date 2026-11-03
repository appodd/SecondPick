import { Link } from "react-router-dom";
import type { ProjectOverview } from "../../api/projectClient";
import { useContextHref } from "./contextNavigation";
import { useGoalContinuity } from "./GoalContinuity";

/** Coverage is not report membership: rule exclusions never become unfinished AI work. */
export function ReportScopeSummary({ data, research = false }: { data: ProjectOverview; research?: boolean }) {
  const href = useContextHref(data.project.id);
  const goal = useGoalContinuity();
  if (!data.report || !data.goal_context?.report_current || goal.state !== "unversioned") return null;
  const counts = [data.coverage.evaluated, data.coverage.summarized, data.coverage.waiting, data.coverage.needs_information];
  const known = counts.every(value => Number.isSafeInteger(value) && value! >= 0);
  const remaining = known ? data.coverage.waiting! + data.coverage.needs_information! : null;
  return <div className="sp-muted" aria-label="当前报告研究范围">
    <p>本报告仅覆盖有限样本，不代表全部商品都已研究。{!known ? "当前覆盖范围暂不可确认。" : null}</p>
    {data.research_work ? <p>{data.research_work.reason}。<Link to={href(`/projects/${data.project.id}?view=research`)}>查看研究安排 →</Link></p> : null}
    {remaining !== null && remaining > 0 ? <p>剩余商品仍保留，未自动全量重研。
      {research ? "可用下方“研究下一个有限批次”分批继续，或在全部商品中选择重点研究。" : <Link to={href(`/projects/${data.project.id}?view=research`)}>继续研究剩余商品 →</Link>}
    </p> : null}
    <details className="sp-copy-help"><summary>查看研究范围</summary><p>目标 v{data.goal_context.current_revision} 的有限样本报告，不代表全库研究完成。{known ? `已逐项分析 ${data.coverage.evaluated} 件，另有 ${data.coverage.summarized} 件仅有批次概述；${remaining} 件等待安排或补充信息。` : "当前研究覆盖数量暂不可确认。"}</p>{data.research_work ? <p>尚未逐项研究 {data.research_work.unassessed} 件，其中 {data.research_work.counts.ready} 件有线索可有限补研。</p> : null}</details>
  </div>;
}
