import type { Report } from "../../api/projectClient";
import { ResponsiveDrawer } from "../../components/layout/ResponsiveDrawer";
import { date } from "./projectUi";
import {useProjectAgent} from './ProjectAgent';
import {candidateIds} from './reportCandidates';

/** The open copy stays stable while the overview continues polling. */
export function FullResearchReport({ report, latest, close, readLatest }: { report: Report; latest: Report | null; close: () => void; readLatest: () => void }) {
  const agent=useProjectAgent();
  return <div className="sp-report-viewer"><ResponsiveDrawer title="完整研究报告" triggerLabel="查看完整研究报告" open onOpenChange={open => { if (!open) close(); }}>
    <article className="sp-full-report">
      <h2>研究报告 #{report.id}</h2>
      {agent.data?<button onClick={()=>{close();agent.open({role:'interpret',ids:candidateIds({...agent.data!,report}),label:`报告 #${report.id} 的已保存背景`,report,reportId:report.id,question:'请解释这份报告的主要结论、依据和仍然存在的局限。'})}}>向 Agent 追问这份报告</button>:null}
      <p className="sp-muted">报告生成 {date(report.created_at)} · 本批输入快照 {date(report.snapshot_at)}</p>
      <p className="sp-muted">{report.goal_revision ? `本报告基于目标 v${report.goal_revision}；只有与项目当前目标版本相同的报告才可作为当前结论。` : "接口尚未返回该报告绑定的选购目标版本，无法独立核验是否适用最新条件。"}</p>
      {report.goal_snapshot ? <details><summary>报告采用的目标与条件</summary><p>{report.goal_snapshot.goal}</p><p>预算上限：{report.goal_snapshot.budget ?? "未设置"} · 硬条件：{report.goal_snapshot.hard.join("；") || "未设置"} · 偏好：{report.goal_snapshot.soft.join("；") || "未设置"}</p></details> : null}
      <p className="sp-muted">这是有限批次研究，不能理解为全库证据均已更新到同一时间。以下保留已保存报告原文。</p>
      {latest && latest.id !== report.id ? <div className="sp-notice sp-report-update" role="status"><p>{latest.id > report.id ? "已有新报告，当前阅读位置和原文保持不变。" : "当前目标另有适用报告；正在阅读的历史报告与位置保持不变。"}</p><button onClick={readLatest}>{latest.id > report.id ? "阅读最新报告" : "查看当前目标报告"}</button></div> : null}
      {report.content.split(/\n\s*\n/).map((block, index) => {
        const heading = block.match(/^#{1,6}\s+([^\n]+)$/);
        return heading ? <h3 key={index}>{heading[1]}</h3> : <p className="sp-report-content" key={index}>{block}</p>;
      })}
    </article>
  </ResponsiveDrawer></div>;
}
