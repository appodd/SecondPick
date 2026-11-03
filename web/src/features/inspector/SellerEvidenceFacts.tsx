import type { ListingEvidence } from "../../api/types";
import { evidenceText, sellerFacts } from "./evidencePresentation";

export function SellerEvidenceFacts({ evidence, profile = {}, observedAt }: {
  evidence?: ListingEvidence; profile?: Record<string, string>; observedAt?: string | null;
}) {
  const facts = evidence ? sellerFacts(evidence.seller_fields) : [];
  const labels: Record<string, string> = { 卖家芝麻信用: "平台信用展示", 卖家注册时长: "平台注册时长", 作为卖家的好评率: "作为卖家的好评率", "卖家在售/已售商品数": "平台在售/已售商品数（原字段）" };
  const saved = Object.entries(labels).flatMap(([key, label]) => {
    const value = evidenceText(profile[key]);
    return value === null ? [] : [{ key, label, value }];
  });
  return <div className="le-seller-facts">
    {facts.length + saved.length ? <>
      <h4>可用的公开资料</h4>
      <dl className="inspector-facts">{facts.map(fact => <div key={fact.key}><dt>{fact.label}<small>{fact.source}</small></dt><dd>{fact.value}</dd></div>)}
        {saved.map(fact => <div key={fact.key}><dt>{fact.label}<small>监控导入的公开卖家档案</small></dt><dd>{fact.value}</dd></div>)}</dl>
      <p className="evidence-disclaimer">以上为已保存的平台展示，未独立核实；信用展示不是交易安全保证。不同来源的记录可能不一致，需以实际页面核对。</p>
      {facts.some(fact => fact.key === "seller_registered_days" && fact.source.includes("解析")) ? <p className="muted">注册天数为页面解析值，可能由注册年数换算，并非精确注册日期。</p> : null}
    </> : <p className="le-empty">当前没有可展示的卖家公开字段。未取得信息不代表信用差，也不能据此确认交易安全。</p>}
    {observedAt ? <p className="muted">公开资料保存时间：{new Date(observedAt).toLocaleString("zh-CN")}（不是实时查询结果）</p> : null}
  </div>;
}
