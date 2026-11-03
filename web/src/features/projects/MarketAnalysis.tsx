import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { ProjectCard, ProjectOverview } from "../../api/projectClient";
import { dimensions, dimensionNames, histogram, initialScope, marketItems, matchesScope, modelDimensions, priceSummary, type Dimension, type MarketScope } from "../market/marketAnalysis";
import { money, PriceHistogram } from "../market/PriceHistogram";
import { SnapshotNotice } from "../../components/status/ExecutionStatus";
import { Panel, date } from "./projectUi";
import "./market-analysis.css";
import { useEntryHref } from "./contextNavigation";
import { MarketReferenceSummary } from "../market/MarketReferenceSummary";

function MarketHeading() {
  return <h2 className="sp-market-heading">市场行情参考<span className="sp-market-beta" title="行情分析仍在完善中，统计结果仅供选购参考。">测试版</span></h2>;
}

export function MarketAnalysis({ data, rows, select }: { data: ProjectOverview; rows: ProjectCard[]; select: (id: number) => void }) {
  return data.market ? <ComparableMarket data={data} select={select} /> : <LegacyMarketAnalysis data={data} rows={rows} select={select} />;
}

function ComparableMarket({ data, select }: { data: ProjectOverview; select: (id: number) => void }) {
  const [params,setParams]=useSearchParams();
  const [bin,setBin]=useState<{scope:string;ids:number[]} | null>(null);
  const market=data.market!, reference=market.references[params.get('marketFor') ?? ''];
  const preferred=market.groups[0];
  const group=market.groups.find(g=>g.key===params.get('market_group')) ?? preferred;
  const layer=params.get('market_layer') ?? (reference?.strict.count ? 'strict' : 'broad');
  const ids=reference ? (layer==='strict'?reference.strict:reference.broad).member_ids : group?.member_ids ?? [];
  const items=ids.flatMap(id=>{const card=data.cards.find(c=>c.listing_id===id);return card&&card.price_value!==null?[{card,specs:{},ambiguous:[]}] : [];});
  const distribution=histogram(items,items), summary=reference ? (layer==='strict'?reference.strict:reference.broad).summary : group?.summary ?? priceSummary(items);
  const key=JSON.stringify([reference?.target_id,layer,group?.key,ids]);
  const shown=bin?.scope===key?items.filter(i=>bin.ids.includes(i.card.listing_id)):items;
  const change=(name:string,value:string)=>{const next=new URLSearchParams(params);next.set(name,value);setParams(next,{replace:true});};
  return <div className="sp-market-analysis"><Panel>
    <MarketHeading /><p className="sp-muted">本项目去重商品的保存挂牌，不是成交价。基线按全项目可比条件计算，不随商品搜索或研究状态筛选变化。</p>
    {market.comparison_version === 2 ? <p className="sp-muted">统一口径：明确商品身份与保存属性分层；专用解析仅补充字段，不按品牌合并型号。</p> : null}
    {market.comparison_version !== 2 ? <p className="sp-muted">当前为旧版保存行情口径，不表示已经按新版通用属性重新比较。</p> : null}
    {!reference && params.has('market_group') && !market.groups.some(g=>g.key===params.get('market_group')) ? <p role="status">先前的分组已变化或不可用，当前显示默认分组，请核对比较条件。</p> : null}
    {reference ? <><MarketReferenceSummary reference={reference} select={select} /><label>比较层级 <select aria-label="行情比较层级" value={layer} onChange={e=>change('market_layer',e.target.value)}><option value="broad">宽泛可比层</option><option value="strict">更严格条件对照</option></select></label></>
      : <label>可比商品分组 <select aria-label="可比商品分组" value={group?.key ?? ''} onChange={e=>change('market_group',e.target.value)}>{market.groups.map(g=><option key={g.key} value={g.key}>{g.label} · {g.member_ids.length} 件</option>)}</select></label>}
    {!reference && group?.scope_note ? <p className="sp-muted">{group.scope_note}</p> : null}
    {!items.length ? <p role="status">{reference?.unavailable_reason ?? market.unavailable_reason ?? '当前条件没有足够明确的可比样本'}；不把未识别型号合并成可信行情，也不静默回退到旧混合统计。</p> : <>
      <p>本层 {summary.count} 件 · 中位 {money(summary.median)} · 范围 {money(summary.min)}–{money(summary.max)}。{summary.count<5 ? '样本少，不展示精确排名或价格评分。' : reference ? (layer==='strict'?reference.strict:reference.broad).position : '仅本层配置范围，不能代替全项目行情。'}</p>
      <PriceHistogram data={distribution} candidatePrice={reference?.current_quote?.valid?Number(reference.current_quote.amount):null} selectBin={ids=>setBin({scope:key,ids})} />
    </>}
    <p className="sp-muted">型号、成色和配件来自保存声明；未知信息不等于已核验。当前统计不表示历史 AI 报告已重新评估。重算于 {date(market.as_of)}。</p>
  </Panel><Panel><div className="sp-between"><h2>比较样本 · {shown.length} 件</h2>{bin?.scope===key?<button onClick={()=>setBin(null)}>显示本层全部样本</button>:null}</div>
    <div className="sp-market-samples">{shown.map(({card})=><button key={card.listing_id} onClick={()=>select(card.listing_id)}><span>#{card.listing_id} · {card.title}</span><b>{money(card.price_value)}</b></button>)}</div>
  </Panel></div>;
}

// Compatibility for older saved API snapshots without the P3 projection.
function LegacyMarketAnalysis({ data, rows, select }: { data: ProjectOverview; rows: ProjectCard[]; select: (id: number) => void }) {
  const [params, setParams] = useSearchParams();
  const entry = useEntryHref(data.project.id);
  const items = useMemo(() => marketItems(data.cards), [data.cards]);
  const candidateId = Number(params.get("marketFor")), candidate = items.find(item => item.card.listing_id === candidateId);
  const [defaults] = useState(() => initialScope(items, data.project.goal, candidate));
  const rawScope = Object.fromEntries(dimensions.map(key => [key, params.get(`market_${key}`) ?? defaults[key]])) as MarketScope;
  const relevant = modelDimensions(rawScope.model);
  const scope = Object.fromEntries(dimensions.map(key => [key, relevant.includes(key) ? rawScope[key] : "__all"])) as MarketScope;
  const [binIds, setBinIds] = useState<number[] | null>(null);
  const [lastScope, setLastScope] = useState("");
  const signature = JSON.stringify([scope, rows.map(card => [card.listing_id, card.price_value])]);
  const allowed = new Set(rows.map(card => card.listing_id));
  const rowOrder = new Map(rows.map((card, index) => [card.listing_id, index]));
  const usable = items.filter(item => !item.excluded);
  const requiresChip = relevant.includes("chip");
  const configured = !!scope.model && (!requiresChip || !!scope.chip);
  const matched = configured ? usable.filter(item => allowed.has(item.card.listing_id) && matchesScope(item, scope) && item.card.listing_id !== candidateId).sort((a, b) => rowOrder.get(a.card.listing_id)! - rowOrder.get(b.card.listing_id)!) : [];
  const summary = priceSummary(matched);
  // All saved items of the same series/chip anchor the bin edges. Text/status/capacity filters do not re-bin.
  const basisScope = { ...scope, memory: "__all", storage: "__all", screen: "__all", year: "__all" };
  const basis = usable.filter(item => matchesScope(item, basisScope));
  const distribution = histogram(basis, matched);
  const changed = dimensions.filter(key => scope[key] !== defaults[key]);
  const relaxed = dimensions.filter(key => defaults[key] !== "__all" && defaults[key] !== "" && scope[key] === "__all");
  const unknown = dimensions.filter(key => !candidate?.specs[key]);
  const differences = candidate ? dimensions.filter(key => candidate.specs[key] && scope[key] && scope[key] !== "__all" && scope[key] !== candidate.specs[key]) : [];
  const needsCapacity = /MacBook|iMac|Mac |ThinkPad|iPhone/.test(scope.model);
  const limited = summary.count < 8 || scope.model.startsWith("__") || (requiresChip && (scope.chip.startsWith("__") || scope.chip.includes("未明确"))) || matched.some(item => item.ambiguous.length > 0) || (needsCapacity && [scope.memory, scope.storage].some(value => !value || value.startsWith("__"))) || (/MacBook|iMac|ThinkPad/.test(scope.model) && scope.screen.startsWith("__")) || (candidate && ((requiresChip && unknown.includes("chip")) || candidate.excluded || !matchesScope(candidate, scope)));
  const latest = matched.map(item => item.card.updated_at).filter((value): value is string => !!value && Number.isFinite(Date.parse(value))).sort((a, b) => Date.parse(a) - Date.parse(b)).at(-1);
  const shown = lastScope === signature && binIds !== null ? matched.filter(item => binIds.includes(item.card.listing_id)) : matched;
  function update(values: Partial<MarketScope>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) next.set(`market_${key}`, value!);
    setParams(next, { replace: true });
  }
  function options(key: Dimension) {
    const values = new Set(items.filter(item => key === "model" || scope.model === "__all" || item.specs.model === scope.model).flatMap(item => item.specs[key] ? [item.specs[key]!] : []));
    if (scope[key] && !scope[key].startsWith("__")) values.add(scope[key]);
    return [...values].sort((a, b) => a.localeCompare(b, "zh-CN", { numeric: true }));
  }
  const selectionLabel = relevant.map(key => scope[key] === "__all" ? `${dimensionNames[key]}未限定` : scope[key] === "__unknown" ? `${dimensionNames[key]}未知` : scope[key]).filter(Boolean).join(" · ");
  return <div className="sp-market-analysis">
    <Panel><div className="sp-between"><div><MarketHeading /><p className="sp-muted">本项目采集样本的挂牌价，不是成交价或全市场公允价。</p></div><span className="sp-market-origin">当前项目 · 去重商品</span></div>
      <p className="sp-muted">旧版快照兼容视图：按旧字段显式筛选展示，不属于新版通用属性的严格分层；新结果不足时不会自动使用这些旧统计填补。</p>
      {params.has("marketFor") && !candidate ? <p role="status">当前项目未返回这件候选的资料，不能确定其配置或价格位置。</p> : null}
      {candidate ? <div className="sp-market-candidate"><div><small>当前候选 · #{candidateId}</small><button className="sp-title-button" onClick={() => select(candidateId)}>{candidate.card.title}</button></div><b>{money(candidate.card.price_value)}</b><p>比较统计排除当前候选本身。配置仅按已保存标题提取，卖家自述尚未独立核实。</p></div> : null}
      {candidate?.excluded ? <p className="sp-market-limit">候选资料限制：{candidate.excluded}，不作精确价格位置判断。</p> : null}
      {differences.length ? <p className="sp-market-limit">当前比较条件与候选不同：{differences.map(key => dimensionNames[key]).join("、")}，不据此判断候选的价格优势。</p> : null}
      <div className="sp-market-filters" aria-label="可比商品配置筛选">{relevant.filter(key => ["model", "chip"].includes(key) || options(key).length > 0).map(key => <label key={key}>{dimensionNames[key]}<select aria-label={`行情${dimensionNames[key]}`} value={scope[key]} onChange={event => {
        if (key === "model") update({ model: event.target.value, chip: "", memory: "__all", storage: "__all", screen: "__all", year: "__all" });
        else update({ [key]: event.target.value });
      }}><option value="">请选择</option><option value="__all">{key === "model" ? "混合型号（仅宽泛概览）" : "不限（范围放宽）"}</option><option value="__unknown">仅未识别项</option>{options(key).map(value => <option key={value} value={value}>{value}</option>)}</select></label>)}</div>
      <p className="sp-market-scope">当前范围：{selectionLabel || "请选择商品系列与处理器"}</p>
      <p className="sp-muted">{changed.length ? `已调整：${changed.map(key => dimensionNames[key]).join("、")}。` : candidate ? "已带入候选标题中可识别的条件；缺失字段不作已知配置。" : "按目标中的明确条件及已观察到的一组配置预选，可手动调整。"}{relaxed.length ? ` 已放宽：${relaxed.map(key => dimensionNames[key]).join("、")}。` : ""}配置按标题提取，属于未核实自述；不同系列或处理器不会自动并入。</p>
      {!configured ? <p role="status">先选择系列与处理器，再生成参考；其他品类可明确选择混合型号或仅未识别项做宽泛查看。</p> : <>
        <div className="sp-market-stats" aria-label="挂牌价核心统计"><div><strong>{summary.count}</strong><span>可用挂牌样本</span></div><div><strong>{money(summary.median)}</strong><span>挂牌价中位数</span></div><div><strong>{summary.q1 === null ? "—" : `${money(summary.q1)} – ${money(summary.q3)}`}</strong><span>中间 50% 的挂牌价（Q1–Q3）</span></div></div>
        {limited ? <p className="sp-market-limit" role="status">{summary.count < 8 ? "可比样本不足 8 件，仅作有限参考。" : "当前范围含配置缺失或未限定条件，仅作有限参考。"}不据此判断市场合理价或购买价值。</p> : <p className="sp-muted">同一标题配置分组仍可能存在成色、电池、维修史、年份与交易条件差异；不等于实物同配置。</p>}
        {summary.count < 8 && ["memory", "storage", "screen", "year"].some(key => !scope[key as Dimension].startsWith("__")) ? <button onClick={() => update({ memory: "__all", storage: "__all", screen: "__all", year: "__all" })}>仅按同系列与处理器比较（放宽容量、尺寸和年份）</button> : null}
        {summary.count ? <><h3>挂牌价格区间分布</h3><p className="sp-muted">每区间 {money(distribution.step)}；同系列/处理器内固定步长，调整容量、文本或研究状态筛选不会改变边界。点击柱形查看商品。</p><PriceHistogram data={distribution} candidatePrice={candidate?.excluded ? null : candidate?.card.price_value} selectBin={ids => { setBinIds(ids); setLastScope(signature); }} />{candidate && !candidate.excluded && candidate.card.price_value !== null && (candidate.card.price_value < distribution.min || candidate.card.price_value > distribution.max) ? <p className="sp-muted">候选价在图示价格范围之外，标记位于{candidate.card.price_value < distribution.min ? "左" : "右"}边缘；具体价格以候选旁数值为准。</p> : null}</> : <p>当前范围没有可用于统计的挂牌样本。可调整配置或上方文本、研究状态筛选；不会自动混入其他芯片。</p>}
        {candidate ? <div className="sp-market-position" aria-label="候选挂牌价位置"><strong>候选挂牌价：{money(candidate.card.price_value)}</strong><p>{candidate.excluded || candidate.card.price_value === null || candidate.card.price_value <= 0 ? "当前候选报价或配置不明确，不能精确标记与判断位置。" : !summary.count ? "没有其他可用样本，无法确定相对位置。" : limited ? "图中细线仅标记候选挂牌价；样本或配置可比性不足，暂不判定偏低或偏高。" : candidate.card.price_value < summary.q1! ? "低于本组样本的下四分位数（Q1）。" : candidate.card.price_value > summary.q3! ? "高于本组样本的上四分位数（Q3）。" : "位于本组样本中间 50% 的挂牌价格区间。"}</p><p>低挂牌价不等于成交便宜或商品可靠；需结合配置、成色、电池、维修及交易条件核实。</p></div> : null}
      </>}
      <p className="sp-market-time">本组最新入库快照：{latest ? date(latest) : "时间未提供"}（不等于挂牌价核验时间）。当前是否仍在售、实际成交价和完整报价观察时间未统一提供。</p><SnapshotNotice />
      <details className="sp-market-method"><summary>统计口径、排除与证据局限</summary><p>来源：原项目 overview 返回的 {data.cards.length} 件当前去重商品；上方文本/研究状态筛选后 {rows.length} 件。统计使用各商品当前保存的 price_value，非历史报价次数，不按卖家或相似库存再次去重。</p><p>前端保守排除无有效正数价格、价格区间、标题明确的服务/配件及核心配置不唯一记录，共 {items.filter(item => item.excluded).length} 件（全项目）。排除不等于商品有风险；没有自动低价阈值，未知在售状态也不伪装为已核实在售。</p><p>配置来自标题规则提取，未使用未经确认的 AI 参数，也没有额外抓取；多型号、多芯片或容量冲突不强选一个。年份或尺寸冲突只记为未知，不直接剔除；宽泛查看时明确降级参考。未知字段不当作匹配已知配置。其他品类需要扩展标题适配器或明确选择宽泛范围。</p><p>分位数沿用原价格统计的线性插值口径，展示保留至分；直方图区间使用 1/2/5 × 10ⁿ 元的整齐步长约分 8 档，左闭右开，最后一档含上界。极值保留，不截掉不利样本。</p><p>本组最低 {money(summary.min)} · 最高 {money(summary.max)}。AI 报告快照 {data.report ? date(data.report.snapshot_at) : "尚无报告"} 与本次统计的入库时间不同；当前没有与此筛选分组绑定的可靠 AI 行情解读，不新增 AI 调用。</p><Link to={entry(`/tasks/${data.project.id}?tab=market`)}>查看原有市场统计与采集诊断 ↗</Link><p><Link to={entry(`/tasks/${data.project.id}?tab=conversation`)}>需要解释价格差异？到统一 Agent 审查研究范围 ↗</Link></p>
        <ul>{items.filter(item => item.excluded).map(item => <li key={item.card.listing_id}><button onClick={() => select(item.card.listing_id)}>商品 #{item.card.listing_id}</button>：{item.excluded}</li>)}</ul>
      </details>
    </Panel>
    {configured ? <Panel><div className="sp-between"><h2>比较样本 · {shown.length} 件</h2>{lastScope === signature && binIds !== null ? <button onClick={() => setBinIds(null)}>显示全部比较样本</button> : null}</div><p className="sp-muted">点击查看原商品及证据；挂牌价和配置均须进一步核实。</p><div className="sp-market-samples">{shown.map(item => <button key={item.card.listing_id} onClick={() => select(item.card.listing_id)}><span>{item.card.title}<small>{dimensions.map(key => item.specs[key]).filter(Boolean).join(" · ")} · 标题自述</small></span><b>{money(item.card.price_value)}</b></button>)}</div></Panel> : null}
  </div>;
}
