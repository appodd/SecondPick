import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { projectApi, type Study } from "../../api/projectClient";
import type { ListingEvidence } from "../../api/types";
import { SellerEvidenceFacts } from "../inspector/SellerEvidenceFacts";
import { evidenceText } from "../inspector/evidencePresentation";
import { StatusBadge } from "../../components/status/ExecutionStatus";
import { studyStatus } from "../../components/status/statusModel";
import { useEntryHref } from "./contextNavigation";

export function SellerResearch({ id, listing, evidence, studies = [] }: { id: number; listing: number; evidence?: ListingEvidence; studies?: Study[] }) {
  const entry = useEntryHref(id);
  const query = useQuery({ queryKey: ["project", id, "seller", listing], queryFn: () => projectApi.seller(id, listing), refetchInterval: 5000 });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const data = query.data;
  const runs = studies.filter(value => data?.seller_id && value.kind === `seller:${data.seller_id}`).sort((a, b) => b.id - a.id);
  const active = runs.find(value => ["queued", "running"].includes(value.state));
  async function study() {
    setBusy(true); setMessage(""); setError("");
    try {
      const result = await projectApi.studySeller(id, listing);
      setMessage("id" in result ? `卖家研究 AgentRun #${result.id} 已受理；可到 Agent 研究查看进度。` : "已复用该卖家的有效档案。");
      await query.refetch();
    } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  return <div className="le-seller-research">
    {query.isLoading ? <p role="status">正在读取已保存的卖家资料…</p> : query.error ? <p role="alert">卖家研究档案暂不可读取，不能据此判断研究是否完成。<button onClick={() => query.refetch()}>重试</button></p> : data ? <>
      {active ? <StatusBadge status={studyStatus(active)} live /> : null}
      {!active && runs[0]?.state === "failed" ? <><StatusBadge status={studyStatus(runs[0])} /><p>本次研究未完成，已有资料仍可查看；执行失败不是卖家信用结论。</p></> : null}
      {data.result ? <>
        <h4>已保存的研究摘要</h4>
        <p><strong>{{ personal_like: "偏个人闲置", commercial_like: "持续经营倾向", unknown: "已分析，经营倾向证据仍不足" }[data.result.business_tendency] ?? "经营倾向暂不可确认"}</strong></p>
        {evidenceText(data.result.reason) ? <p className="message-content">{data.result.reason}</p> : null}
        <p className="evidence-disclaimer">经营倾向属于 AI 对已保存公开信息的分析，不是身份核验；持续经营也不自动等于交易风险。</p>
        <h4>交易疑点</h4>{data.result.risk_clues.some(value => evidenceText(value)) ? <ul>{data.result.risk_clues.filter(value => evidenceText(value)).map((value, index) => <li key={index}>{value}</li>)}</ul> : <p>本次研究未列出具体疑点，不代表没有风险。</p>}
        <h4>仍待核实</h4>{data.result.unknowns.some(value => evidenceText(value)) ? <ul>{data.result.unknowns.filter(value => evidenceText(value)).map((value, index) => <li key={index}>{value}</li>)}</ul> : <p>研究未提供进一步核实清单，仍需确认商品来源与实物状态。</p>}
        <p className="le-limit">{data.fresh ? "档案在后端有效期内，且保存资料未变化；不代表实时平台或线下核验。" : "历史研究档案已过期或公开资料有变化，请重新分析后再参考。"}</p>
        {data.researched_at ? <p className="muted">研究保存于 {new Date(data.researched_at).toLocaleString("zh-CN")}</p> : null}
      </> : <div className="le-empty"><p>尚无已完成的卖家研究结论。</p><p>{data.seller_id ? "可先参考下方已保存的公开资料，再按需分析。" : "尚无可关联的公开卖家 ID，不能按昵称合并档案。"}资料为空不代表卖家信用差。</p><p>当前接口没有完整调查尝试记录，不能仅凭空字段断言从未调查或调查失败。</p></div>}
    </> : null}
    <SellerEvidenceFacts evidence={evidence} profile={query.isError ? {} : data?.profile} observedAt={query.isError ? null : data?.observed_at} />
    {data && !query.isError ? <>
      <button disabled={busy || !!active || !data.seller_id} onClick={() => void study()}>{busy ? "提交中…" : active ? "已有卖家研究任务" : data.fresh ? "复用已有研究档案" : "分析已保存的卖家资料"}</button>
      <p className="muted">仅分析已保存资料，不自动访问卖家主页或补抓。</p>
      <details><summary>卖家档案来源与关联信息</summary><p>公开卖家 ID：{evidenceText(data.seller_id) ?? "尚未获得可关联 ID"}</p><p>监控导入的公开卖家档案，仅覆盖本机已保存字段，不包含完整发布或私人交易记录。</p>
        {Object.entries(data.profile).filter(([, value]) => evidenceText(value)).map(([key, value]) => <p key={key}>{key}：{value}</p>)}</details>
    </> : null}
    {message ? <p role="status">{message}</p> : null}{error ? <p role="alert" className="le-limit">{error}</p> : null}
    <p><Link to={entry(`/tasks/${id}?tab=conversation&listing=${listing}&context=open`)}>需要补充调查？到统一 Agent 审查采集范围与权限 ↗</Link></p>
  </div>;
}
