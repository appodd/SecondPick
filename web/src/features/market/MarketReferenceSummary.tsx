import type { MarketReference } from "../../api/projectClient";
import { money } from "./PriceHistogram";

export function MarketReferenceSummary({ reference, select, compact = false }: { reference?: MarketReference; select?: (id: number) => void; compact?: boolean }) {
  if (!reference) return null;
  const q = reference.current_quote;
  return <div className="sp-local-market" aria-label={`商品 ${reference.target_id} 挂牌参考`}>
    <p><strong>当前保存挂牌：{q?.valid ? money(Number(q.amount)) : "待确认"}</strong>{compact ? ` · 宽泛参考 ${reference.broad.count} 件，中位 ${money(reference.broad.summary.median)}` : null}</p>
    {reference.unavailable_reason ? <p role="status">无法建立可靠同款基线：{reference.unavailable_reason}。</p> : null}
    {!compact ? <><p>宽泛可比 {reference.broad.count} 件 · 中位 {money(reference.broad.summary.median)} · {reference.broad.position}</p>
      <p>当前明确维度的严格对照 {reference.strict.count} 件 · 中位 {money(reference.strict.summary.median)} · {reference.strict.position}（宽泛层的子集）</p></> : null}
    <details><summary>样本条件、来源与限制</summary>
      <p>宽泛：{reference.criteria.broad}。更严格：{reference.criteria.strict}。</p>
      <p>其他商品 {reference.peer_total} 件，宽泛排除 {reference.excluded_count} 件；目标自身不参与统计。</p>
      <p>报价时点：{q?.observed_at ?? "未提供"} · {q?.time_basis === "recorded_time_fallback" ? "来源时间不可直接比较，按保存时间有限排序" : "按保存的观察时间"}。统计重算：{new Date(reference.as_of).toLocaleString("zh-CN")}。</p>
      {q?.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
      <ul>{reference.limitations.map((limit, index) => <li key={index}>{limit}</li>)}</ul>
      <p>这是当前本地挂牌统计，不表示 AI 已用这些数据更新历史判断或建议购买。</p>
      {Object.entries(reference.exclusion_counts).map(([reason, count]) => <p key={reason}>{reason}：{count} 件</p>)}
      {select ? <details><summary>查看真实比较商品与排除原因</summary>
        <p>宽泛样本：{reference.broad.member_ids.map(id => <button key={id} onClick={() => select(id)}>#{id}</button>)}</p>
        <p>更严格样本：{reference.strict.member_ids.map(id => <button key={id} onClick={() => select(id)}>#{id}</button>)}</p>
        <ul>{reference.excluded.map(item => <li key={item.listing_id}><button onClick={() => select(item.listing_id)}>#{item.listing_id}</button>：{item.reason}</li>)}</ul>
      </details> : null}
    </details>
  </div>;
}
