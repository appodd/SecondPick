import { useState, type ReactNode } from "react";
import type { ListingEvidence, TaskDetail } from "../../api/types";
import type { ProjectOverview } from "../../api/projectClient";
import { EvidenceStatus } from "./EvidenceStatus";
import { X } from "lucide-react";
import { CandidateChecks } from "./CandidateChecks";
import { ProductGallery } from "../projects/ProductImages";
import { ProductMediaGallery } from "../projects/ProductMediaGallery";
import { evidenceText, productQuestions, sourceLabel } from "./evidencePresentation";
import { SellerEvidenceFacts } from "./SellerEvidenceFacts";
import { ListingResearchSummary } from "./ListingResearchSummary";
import { MarketReferenceSummary } from "../market/MarketReferenceSummary";
import "./listing-evidence.css";
import { VisualEvidence } from "./VisualEvidence";
import { useProjectAgent } from "../projects/ProjectAgent";
import { visualQuestionScope } from "./visualQuestion";

export function ListingEvidencePanel({ evidence, onClose, taskId, imageUrls = [], imagesComplete = false, project, task, sellerResearch, marketReference, beforeQuestion }: {
  evidence: ListingEvidence; onClose?: () => void; taskId?: number; imageUrls?: string[]; imagesComplete?: boolean;
  project?: ProjectOverview; task?: TaskDetail; sellerResearch?: ReactNode; marketReference?: () => void;beforeQuestion?:()=>void;
}) {
  const [expandedTitle, setExpandedTitle] = useState<number>();
  const agent = useProjectAgent();
  const questions = productQuestions(evidence);
  const attributes = Object.entries(evidence.detail?.attributes ?? {}).flatMap(([key, raw]) => {
    const value = evidenceText(raw); return value !== null ? [{ key, value }] : [];
  });
  const configurations = attributes.filter(item => /品牌|型号|处理器|内存|容量|存储|硬盘|尺寸/.test(item.key)).slice(0, 4);
  const description = evidenceText(evidence.detail?.description) ?? (evidence.search_description_status === "distinct" ? evidenceText(evidence.search_description) : null);
  const statements = evidence.user_statements ?? [];
  const price = evidenceText(evidence.price_text);
  const priceLabel = evidence.current_quote && !evidence.current_quote.valid ? "价格待确认" : price ? (/^\d+(\.\d+)?$/.test(price) ? `¥${price}` : price) : evidence.price_value !== null && Number.isFinite(evidence.price_value) ? `¥${evidence.price_value.toLocaleString("zh-CN")}` : "价格待确认";
  return <section className="listing-evidence" aria-labelledby="listing-evidence-title">
    <div className="inspector-section-heading">
      <p>商品详情 · 选购辅助</p><h2 id="listing-evidence-title" className={expandedTitle === evidence.listing_id ? "" : "le-title-collapsed"}>{evidenceText(evidence.title) ?? "商品名称待补充"}</h2>
      {evidence.title.length > 85 ? <button className="le-title-toggle" aria-expanded={expandedTitle === evidence.listing_id} onClick={() => setExpandedTitle(expandedTitle === evidence.listing_id ? undefined : evidence.listing_id)}>{expandedTitle === evidence.listing_id ? "收起长标题" : "显示完整标题"}</button> : null}
      {onClose && <button type="button" className="icon-button inspector-close" aria-label="关闭商品证据" title="关闭商品证据" onClick={onClose}><X size={18} aria-hidden="true" /></button>}
    </div>
    {taskId !== undefined ? <SavedProductGallery key={evidence.listing_id} taskId={taskId} evidence={evidence} fallback={imageUrls} />
      : <ProductGallery key={evidence.listing_id} images={imageUrls} title={evidence.title} complete={imagesComplete} />}
    <div className="le-product-basics">
      <strong className="le-price">{priceLabel}</strong><p className="muted">商品 #{evidence.listing_id}</p>
      <div className="le-meta">{[evidenceText(evidence.location), evidenceText(evidence.search_condition), evidenceText(evidence.seller_name) ? `卖家：${evidenceText(evidence.seller_name)}` : null].filter(Boolean).map((value, index) => <span key={index}>{value}</span>)}</div>
      {configurations.length ? <dl className="inspector-facts le-configuration">{configurations.map(item => <div key={item.key}><dt>{item.key}</dt><dd>{item.value}</dd></div>)}</dl> : <p className="muted">关键规格尚待确认，不能仅凭标题认定配置。</p>}
      {configurations.length ? <p className="muted">配置来自商品页面中的已保存属性，是否与实物一致仍需核实。</p> : null}
      <a href={evidence.url} rel="noreferrer" target="_blank">打开原始商品链接 ↗</a>
      {marketReference ? <button onClick={marketReference}>查看行情参考</button> : null}
    </div>

    <ListingResearchSummary evidence={evidence} project={project} task={task} />
    {taskId !== undefined && project ? <VisualEvidence key={`visual-${taskId}-${evidence.listing_id}`} taskId={taskId} listingId={evidence.listing_id} onQuestion={agent.data ? o=>{beforeQuestion?.();agent.open(visualQuestionScope(o));} : undefined} /> : null}
    <MarketReferenceSummary reference={project?.market?.references[String(evidence.listing_id)]} compact />
    {questions.length ? <section className="inspector-block"><h3>建议向卖家确认</h3><ul className="compact-list">{questions.map(question => <li key={question}>{question}</li>)}</ul><p className="muted">信息待核实，不代表商品不合格。</p></section> : null}
    {taskId !== undefined ? <CandidateChecks key={`${taskId}:${evidence.listing_id}`} taskId={taskId} listingId={evidence.listing_id} /> : null}

    <section className="inspector-block" aria-label="商品详细信息"><div className="le-section-heading"><h3>商品详细信息</h3><EvidenceStatus status={evidence.detail_status} /></div>
      {description ? <><h4>商品描述</h4><p className="message-content le-description">{description}</p><p className="evidence-disclaimer">{evidenceText(evidence.detail?.description) ? "来源：已保存商品详情中的卖家自述" : "来源：已保存搜索卡片中的商品描述"}，未独立核实。</p></>
        : <p className="le-empty">{evidence.detail_status === "blocked" ? "详情访问未成功，当前没有可用的商品描述。" : evidence.detail_status === "not_captured" ? "尚未采集到有效商品详情，可先查看原始链接或审查补抓范围。" : "已有详情采集记录，但没有可展示的描述文本。"}</p>}
      {attributes.length ? <><h4>页面中的商品属性</h4><dl className="inspector-facts">{attributes.map(item => <div key={item.key}><dt>{item.key}</dt><dd>{item.value}</dd></div>)}</dl>
        <p className="evidence-disclaimer">来源：{sourceLabel(evidence.detail?.attributes_source ?? evidence.detail?.evidence_source)} · {evidence.detail?.independently_verified ? "接口标注已独立核验；核验范围以保存证据为准。" : "详情属性未独立验证。"}</p></> : null}
      {evidence.evidence_conflicts.length ? <details className="le-conflicts"><summary>有 {evidence.evidence_conflicts.length} 项来源记录不一致，需要核实</summary><ul>{evidence.evidence_conflicts.map((item, i) => <li key={i}>{item.field}：{evidenceText(item.selected_value) ?? "未提供有效值"}（{sourceLabel(item.selected_source)}） / {evidenceText(item.conflicting_value) ?? "未提供有效值"}（{sourceLabel(item.conflicting_source)}）</li>)}</ul><p>记录冲突并不自动证明哪一方正确。</p></details> : null}
    </section>

    {statements.length ? <section className="inspector-block" aria-label="绑定的用户补充证据"><h3>用户补充证据</h3>
      <p className="evidence-disclaimer">由用户提供，未经独立核实；不会自动消除旧证据中的冲突。</p>
      <ul className="le-statements">{statements.slice(0, 3).map(statement => <li key={statement.id}><strong>{statement.kind === "seller_reply" ? "用户转述卖家答复" : "用户本人观察"}</strong><p className="message-content">{evidenceText(statement.statement_text) ?? "这条补充没有有效文本。"}</p></li>)}</ul>
      {statements.length > 3 ? <details><summary>查看其余 {statements.length - 3} 条补充</summary>{statements.slice(3).map(statement => <div key={statement.id}><strong>{statement.kind === "seller_reply" ? "用户转述卖家答复" : "用户本人观察"}</strong><p className="message-content">{evidenceText(statement.statement_text) ?? "这条补充没有有效文本。"}</p></div>)}</details> : null}
      {evidence.user_statements_truncated ? <p className="muted">共 {evidence.user_statement_count} 条，仅展示最近 20 条；较早原文仍在对话历史中。</p> : null}
    </section> : null}

    <section className="inspector-block" aria-label="卖家研究"><h3>卖家研究</h3>
      {sellerResearch ?? <><p className="le-empty">尚无可用的卖家研究结论。当前详情接口不包含研究尝试记录，暂不能确认是否曾调查。</p><SellerEvidenceFacts evidence={evidence} />
        {taskId !== undefined ? <a href={`/tasks/${taskId}?tab=conversation&listing=${evidence.listing_id}&context=open`}>到统一 Agent 审查商品与卖家调查范围 ↗</a> : null}</>}
      {evidence.seller_other_items.length ? <details><summary>查看已保存的卖家其他商品（{evidence.seller_other_items.length}）</summary><ul>{evidence.seller_other_items.map((item, index) => <li key={index}>{evidenceText(item.title) ?? "商品名称未提供"}</li>)}</ul><p className="muted">仅为本机已保存记录，不代表完整发布历史，也不能把下架推断为成交。</p></details> : null}
    </section>

    <details className="inspector-block le-diagnostics"><summary>详细证据与采集记录</summary>
      <p className="muted">采集计数反映保存记录，不等于内容已核实，也不代表采集失败或商品风险。</p>
      <dl className="inspector-facts"><div><dt>关联采集批次</dt><dd>{evidence.source_run_ids.map(value => `#${value}`).join("、") || "尚无批次编号"}</dd></div>
        {evidence.detail ? <><div><dt>选用详情快照</dt><dd>#{evidence.detail.snapshot_id} · 采集批次 #{evidence.detail.run_id}</dd></div><div><dt>属性来源</dt><dd>{sourceLabel(evidence.detail.attributes_source)}</dd></div></> : null}
        <div><dt>详情快照记录</dt><dd>{evidence.collection_state.detail_snapshot_count}</dd></div><div><dt>有效详情记录</dt><dd>{evidence.collection_state.valid_detail_snapshot_count}</dd></div><div><dt>受阻详情记录</dt><dd>{evidence.collection_state.blocked_detail_snapshot_count}</dd></div>
        <div><dt>已保存的商品图片记录（商品历史范围）</dt><dd>{evidence.collection_state.listing_lifetime_product_image_count}</dd></div><div><dt>已下载图片</dt><dd>{evidence.collection_state.listing_lifetime_downloaded_product_image_count}</dd></div><div><dt>OCR 结果</dt><dd>{evidence.collection_state.listing_lifetime_ocr_result_count}</dd></div></dl>
      <p className="muted">没有 OCR 结果不等于没有图片；详情采集记录也不保证所有字段可读取。实名认证、回复率等字段是否可获取取决于原采集来源，当前没有字段级可用性声明。</p>
      {evidenceText(evidence.raw_text_excerpt) ? <details><summary>查看已保存的页面文字摘录</summary><p className="message-content">{evidence.raw_text_excerpt}</p><p className="muted">原始页面文本可能含界面标签及卖家自述，不是独立核验证据。</p></details> : null}
    </details>
  </section>;
}

function SavedProductGallery({ taskId, evidence, fallback }: { taskId: number; evidence: ListingEvidence; fallback: string[] }) {
  return <ProductMediaGallery taskId={taskId} listingId={evidence.listing_id} title={evidence.title} fallback={fallback}/>;
}
