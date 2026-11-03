import { useQuery } from "@tanstack/react-query";
import { queries } from "../../api/queries";
import type { CandidateSummary, ListingEvidence, MessageDto } from "../../api/types";

/** Only associate explicitly headed paragraphs, never incidental ID mentions. */
export function candidateCommentary(content: string, id: number) {
  const paragraphs = content.split(/\n\s*\n/).map(value => value.trim());
  const heading = new RegExp(`^(?:\\d+[.、)]\\s*)?(?:(?:优先看|其次看|大容量备选|候选|商品)\\s*)?#?${id}\\s*[:：]`);
  const paragraph = paragraphs.find(value => heading.test(value));
  if (!paragraph) return { reason: null, checks: [] as string[] };
  const sentences = paragraph.replace(heading, "").trim().split(/(?<=[。！？；])\s*/u).filter(Boolean);
  const actionableCheck = /待核实|需核实|需要核实|重点核实|优先核实|核对|异常/;
  const checks = sentences.filter(value => (actionableCheck.test(value) || /未明确|不明确|缺口/.test(value))
    && !( /补上|补齐|填补/.test(value) && !actionableCheck.test(value)));
  const reasons = sentences.filter(value => !checks.includes(value) && /首选|优先|便宜|适合|因此|完整|容量翻倍|预算|备选|弱线索/.test(value));
  return { reason: (reasons.length ? reasons : sentences.filter(value => !checks.includes(value))).slice(0, 2).join(" ") || null, checks: checks.slice(0, 3) };
}

export function comparisonFacts(candidate: CandidateSummary | undefined, evidence: ListingEvidence | undefined) {
  const source = evidence ?? candidate;
  const text = source ? [source.title, source.search_description, evidence?.detail?.description].filter(Boolean).join("\n") : "";
  const capacities = [...new Set([...text.matchAll(/\b(\d+(?:\.\d+)?)\s*(GB|TB|G|T)(?![a-z])/gi)]
    .filter(match => /t/i.test(match[2]) || Number(match[1]) >= 32)
    .map(match => `${match[1]}${/t/i.test(match[2]) ? "TB" : "GB"}`))];
  const pickup = text.split(/[。\n；！？，,]/).filter(value => /自提|面交/.test(value)).map(value => value.trim());
  const specificPickup = pickup.find(value => value !== "可自提" && value.length <= 100) ?? pickup[0];
  return {
    price: source?.price_text ?? "价格未记录",
    storage: evidence?.detail?.attributes["存储容量"] ?? evidence?.detail?.attributes["硬盘容量"] ?? evidence?.detail?.attributes["硬盘"] ?? (capacities.length ? capacities.join(" / ") : "容量未记录"),
    location: source?.location ?? "所在地未记录",
    pickup: specificPickup ?? "自提安排未记录",
  };
}

function ComparisonCard({ id, index, taskId, content, candidate, onSelectListing }: {
  id: number; index: number; taskId: number; content: string; candidate?: CandidateSummary; onSelectListing: (id: number) => void;
}) {
  const evidence = useQuery(queries.listingEvidence(taskId, id));
  const source = evidence.data ?? candidate;
  const facts = comparisonFacts(candidate, evidence.data);
  const commentary = candidateCommentary(content, id);
  const detailState = source?.detail_status;
  return <article className="comparison-card" aria-label={`候选 ${index + 1}，商品 ${id}`}>
    <div className="comparison-card__top"><span>候选 {index + 1}</span><span className="comparison-card__state">{detailState === "captured" ? "已读取详情" : detailState === "blocked" ? "详情读取受阻" : source ? "仅有搜索信息" : "证据待读取"}</span></div>
    <h3>{source?.title ?? `商品 #${id}`}</h3>
    <p className="comparison-card__price">{facts.price}<span>{facts.storage}</span></p>
    <dl className="comparison-card__facts"><div><dt>所在地</dt><dd>{facts.location}</dd></div><div><dt>自提描述</dt><dd>{facts.pickup}</dd></div></dl>
    <div className="comparison-card__reason"><h4>推荐理由</h4><p>{commentary.reason ?? "助手未单列这条的理由，可展开完整分析查看。"}</p></div>
    <div className="comparison-card__checks"><h4>待核实</h4>{commentary.checks.length ? <ul>{commentary.checks.map((value, i) => <li key={i}>{value}</li>)}</ul> : <p>实际机况、卖家身份与交易安排仍需确认，详见完整分析。</p>}</div>
    {evidence.isPending && <p className="muted">正在读取已保存的证据…</p>}
    {evidence.error && <p role="alert" className="scoped-error">详情暂时无法加载，已显示已有信息。<button onClick={() => void evidence.refetch()}>重试</button></p>}
    <button className="comparison-card__evidence" aria-label={`查看${source?.title ?? `商品 #${id}`}的证据`} onClick={() => onSelectListing(id)}>查看商品证据</button>
  </article>;
}

export function ShortlistComparison({ message, candidates, onSelectListing }: {
  message: MessageDto; candidates: CandidateSummary[]; onSelectListing: (id: number) => void;
}) {
  return <section className="shortlist-comparison" aria-label="候选对比">
    <div className="shortlist-comparison__heading"><h2>这轮候选对比</h2><span>{message.candidate_ids.length} 条候选</span></div>
    <p className="shortlist-comparison__note">按助手列出的顺序展示。价格、参数与自提信息来自商品记录，卖家陈述尚未独立核实。</p>
    <div className="comparison-grid">{message.candidate_ids.map((id, index) => <ComparisonCard key={id} id={id} index={index} taskId={message.task_id} content={message.content}
      candidate={candidates.find(item => item.listing_id === id)} onSelectListing={onSelectListing} />)}</div>
  </section>;
}
