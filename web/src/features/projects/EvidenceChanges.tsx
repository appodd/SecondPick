import type { ProjectOverview } from '../../api/projectClient';

const labels: Record<string,string> = { priority: '值得优先复评', merge: '合并等待研究', not_needed: '目前无需复评', needs_evidence: '需要补充证据', queued: '已安排复评', running: '正在研究', completed: '已完成复评', failed: '复评失败', attempted: '已尝试，待人工处理' };
const fields: Record<string,string> = { title:'商品名称或型号',price:'挂牌价',description:'描述与交易说明',attributes:'商品属性',condition:'成色声明',seller:'平台卖家信息',statements:'用户补充证据' };
export function EvidenceChanges({ data, listing, compact = false }: { data: ProjectOverview; listing?: number; compact?: boolean }) {
  const work = data.evidence_work;
  if (!work) return null;
  const items = work.items.filter(i => listing === undefined || i.listing_id === listing);
  const updates = data.integration_work?.updates?.filter(i => listing === undefined || i.item.listing_id === listing) ?? [];
  if (!items.length && !updates.length && data.integration_work?.state === 'none' && data.report?.evidence_current !== false) return null;
  return <section className={compact ? 'sp-muted' : 'sp-panel'} aria-label="新证据与有限复评">
    <strong>商品信息更新</strong>
    <p>{work.reason}。{items.length} 件有证据变化。图片已保存不代表 AI 已看图。</p>
    {data.report?.evidence_current === false ? <p role="status">当前综合报告仍基于原证据快照；部分候选证据已更新，不能把旧建议当作最新判断。</p> : null}
    {data.integration_work && !['none','current'].includes(data.integration_work.state) ? <p role="status">{data.integration_work.reason}。不会用单件小结替换综合报告。</p> : null}
    {items.length ? <details><summary>查看变化、旧判断与复评原因</summary><p>每批最多研究 {work.batch_limit} 件；是否执行仍取决于当前授权与研究状态。</p><ul>{items.map(item => <li key={item.listing_id}>
      <strong>#{item.listing_id} · {labels[item.state] ?? item.state}</strong><p>{item.reason}</p>
      <p>原判断（AgentRun #{item.previous.study_id}）：{item.previous.assessment?.summary ?? '只有批次概述，没有有效逐项判断'}</p>
      <details><summary>本次变化字段：{item.delta.fields.map(key=>fields[key] ?? key).join('、') || '无可用新事实'}</summary><pre className="sp-report-content">{JSON.stringify({ 原有证据: item.delta.before, 当前证据: item.delta.after }, null, 2)}</pre></details>
    </li>)}</ul></details> : null}
    {!compact && updates.length ? <details><summary>查看已完成的新判断（保留历史）</summary><ul>{updates.map(i => <li key={i.item.listing_id}>#{i.item.listing_id} · AgentRun #{i.study_id}：{i.assessment.summary}
      {i.decision_impacts?.length ? <ul>{i.decision_impacts.map(change => <li key={change.criterion_id}>条件 {change.criterion_id}：{change.before} → {change.after} · {change.reason}<p>依据变化：{change.changed_fields.map(key => fields[key] ?? key).join('、')} · 引用 {change.evidence_refs.length} 条（不代表独立来源数量）</p></li>)}</ul> : <p className="sp-muted">尚未满足自动整合的依据要求；请核对实际变化，再次提名或证据说明完善不自动重写综合报告。</p>}
    </li>)}</ul></details> : null}
  </section>;
}
