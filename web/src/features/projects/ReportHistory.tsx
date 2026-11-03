import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { projectApi, type ProjectOverview, type Report } from "../../api/projectClient";
import { FullResearchReport } from "./FullResearchReport";
import { date } from "./projectUi";

export function ReportHistory({ data }: { data: ProjectOverview }) {
  const [open, setOpen] = useState(false), [reading, setReading] = useState<Report | null>(null);
  const query = useInfiniteQuery({ queryKey: ["project",data.project.id,"report-history"], queryFn: ({ pageParam }) => projectApi.reports(data.project.id,pageParam), initialPageParam: undefined as number | undefined, getNextPageParam: page => page.next_before_id ?? undefined, enabled: open });
  return <><details className="sp-panel sp-research-secondary" onToggle={event => setOpen(event.currentTarget.open)}><summary>历史研究报告</summary>
    <p>历史报告、原目标和原研究结果保留；不同目标版本的报告不能混作当前建议。</p>
    {query.isPending ? <p role="status">正在读取报告历史…</p> : null}
    {query.error ? <p role="alert">{query.error.message}<button onClick={() => void query.refetch()}>重试报告历史</button></p> : null}
    {query.data?.pages.flatMap(page => page.items).map(report => <p key={report.id}><button onClick={() => setReading(report)}>报告 #{report.id} · {report.goal_revision ? `目标 v${report.goal_revision}` : "目标版本未核验"} · {date(report.created_at)}</button></p>)}
    {query.data?.pages[0].items.length === 0 ? <p>尚无已保存报告。</p> : null}
    {query.hasNextPage ? <button disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>加载更早报告</button> : null}
  </details>{reading ? <FullResearchReport report={reading} latest={data.report} close={() => setReading(null)} readLatest={() => { if (data.report) setReading(data.report); }} /> : null}</>;
}
