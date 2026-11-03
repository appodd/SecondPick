import {AutoCoverCache} from './AutoCoverCache';
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search, Bookmark, ArrowUpRight, Columns3 } from "lucide-react";
import { projectApi, type ProjectOverview } from "../../api/projectClient";
import { Panel, label, price, ProductThumbnail } from "./projectUi";
import { productInsights, matchLabels, aiLabels } from "./productInsights";
import { ConditionCell, ProductOverviewStats, ResearchCell } from "./ProductInsightsView";
import { useGoalContinuity } from "./GoalContinuity";
import { MarketAnalysis } from "./MarketAnalysis";
import { marketHref } from "../market/marketAnalysis";
import { useContextHref } from "./contextNavigation";
import { useProjectAgent } from "./ProjectAgent";

import { filteredProducts, productAgentScope } from "./agentContext";
import { EvidenceChanges } from "./EvidenceChanges";
import { optionalProductColumns, productColumns, type ProductColumn } from "./productColumns";
import "./shopping-workbench.css";

export function Products({
  data,
  selected: selection,
  setSelected,
  select,
  action,
  busy,
}: {
  data: ProjectOverview;
  selected: number[];
  setSelected: (ids: number[]) => void;
  select: (id: number) => void;
  action: (fn: () => Promise<unknown>) => Promise<void>;
  busy: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const agent = useProjectAgent();
  const navigate=useNavigate(),favoriteLock=useRef(false);
  const [filtersOpen,setFiltersOpen]=useState(false);
  const fieldPicker = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    function outside(event: PointerEvent) {
      const picker = fieldPicker.current;
      if (picker?.open && event.target instanceof Node && !picker.contains(event.target)) picker.open = false;
    }
    function escape(event: KeyboardEvent) {
      const picker = fieldPicker.current;
      if (event.key !== "Escape" || !picker?.open) return;
      picker.open = false;
      if (picker.contains(document.activeElement)) {
        event.preventDefault();
        picker.querySelector("summary")?.focus();
      }
    }
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  const goal = useGoalContinuity();
  const search = params.get("q") ?? "";
  const [searchInput, setSearchInput] = useState(search);
  const composing = useRef(false), committedSearch = useRef(search);
  useEffect(() => { if (!composing.current) { setSearchInput(search); committedSearch.current = search; } }, [search]);
  function commitSearch(value: string) { if (committedSearch.current === value) return; committedSearch.current = value; update({ q: value, page: "0" }); }
  const filter = params.get("state") ?? "all";
  const display = params.get("display") ?? "table";
  const grid = display === "cards";
  const contextual = useContextHref(data.project.id);
  function update(values: Record<string, string>) { const next = new URLSearchParams(params); for (const [key, value] of Object.entries(values)) next.set(key, value); if (next.toString() !== params.toString()) setParams(next, { replace: true }); }
  function setDisplay(value: string) {
    if (value === display) return;
    if (value === "market" && display !== "market") {
      const target = new URL(contextual(marketHref(data.project.id)), "https://secondpick.local");
      for (const key of ["q", "state", "sort", "match", "ai"]) if (params.has(key)) target.searchParams.set(key, params.get(key)!);
      setParams(target.searchParams);
    } else { const next = new URLSearchParams(params); next.set("display", value); for (const key of [...next.keys()]) if (key.startsWith("market") || (key === "returnTo" && display === "market")) next.delete(key); setParams(next); }
  }
  const sort = ["price", "match", "ai"].includes(params.get("sort") ?? "") ? params.get("sort")! : "new";
  const activeFilterCount=[filter!=='all',!!params.get('match')&&params.get('match')!=='all',!!params.get('ai')&&params.get('ai')!=='all',sort!=='new'].filter(Boolean).length;
  const requestedPage = Number(params.get("page") ?? 0);
  const columns=productColumns(params),fields=columns.includes('match');
  const show=(column:ProductColumn)=>columns.includes(column);
  function toggleColumn(column:ProductColumn){update({columns:(show(column)?columns.filter(c=>c!==column):[...columns,column]).join(',')})}
  const insights = useMemo(() => productInsights(data, goal.state === "unversioned"), [data, goal.state]);
  const rows = useMemo(() => filteredProducts(data, params, insights), [data, params, insights]);
  const pageCount = Math.ceil(rows.length / 40);
  const page = Math.min(Number.isSafeInteger(requestedPage) && requestedPage >= 0 ? requestedPage : 0, Math.max(0, Math.ceil(rows.length / 40) - 1));
  const visible = rows.slice(page * 40, page * 40 + 40);
  const selected = selection.filter(id => rows.some(card => card.listing_id === id));
  useEffect(() => { if (selected.length !== selection.length) setSelected(selected); }, [rows, selection, setSelected]);
  const selectedMissing=selected.some(id=>!data.cards.some(card=>card.listing_id===id));
  async function favorite(id:number){if(favoriteLock.current||busy)return;favoriteLock.current=true;try{await action(()=>projectApi.favorite(data.project.id,id,!data.favorites.includes(id)))}finally{favoriteLock.current=false}}
  function compareSelected(){if(selected.length<2||selected.length>4||selectedMissing)return;navigate(contextual(`/projects/${data.project.id}?view=shortlist&compare=${selected.join(',')}`))}
  function toggle(id: number) {
    setSelected(
      selected.includes(id)
        ? selected.filter((i) => i !== id)
        : [...selected, id],
    );
  }
  return (
    <div className={`ux2-products${filtersOpen?' is-filter-open':''}`}>

      {display !== "market" ? <ProductOverviewStats data={data} insights={insights} results={rows.length} params={params} update={update} /> : null}
      <div className="sp-toolbar ux-polish-toolbar" aria-label="商品浏览工具">
        <label className="sp-search">
          <Search size={16} />
          <input
            aria-label="搜索商品"
            placeholder="搜索商品、编号、卖家或地区"
            value={searchInput}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={event => { composing.current = false; setSearchInput(event.currentTarget.value); commitSearch(event.currentTarget.value); }}
            onChange={event => { setSearchInput(event.target.value); if (!composing.current && !(event.nativeEvent as InputEvent).isComposing) commitSearch(event.target.value); }}
          />
        </label>
        <button className="ux2-filter-toggle" aria-expanded={filtersOpen} aria-controls="ux2-product-filters" onClick={()=>setFiltersOpen(value=>!value)}>筛选与排序{activeFilterCount?` · ${activeFilterCount}`:''}</button>
        <div id="ux2-product-filters" className="ux2-filter-controls"><select
          aria-label="研究状态筛选"
          value={filter}
          onChange={(event) => update({ state: event.target.value, page: "0" })}
        >
          <option value="all">全部状态</option>
          {[
            "waiting",
            "evaluated",
            "summarized",
            "rule_excluded",
            "needs_information",
            "blocked",
            "queued",
          ].map((state) => (
            <option key={state} value={state}>
              {label(state)}
            </option>
          ))}
        </select>
        <select aria-label="条件匹配筛选" value={params.get("match") ?? "all"} onChange={event => update({ match: event.target.value, page: "0" })}>
          <option value="all">全部条件匹配</option>{Object.entries(matchLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
        </select>
        <select aria-label="AI 判断筛选" value={params.get("ai") ?? "all"} onChange={event => update({ ai: event.target.value, page: "0" })}>
          <option value="all">全部 AI 判断</option>{Object.entries(aiLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
        </select>
        <select
          aria-label="商品排序"
          value={sort}
          onChange={(event) => update({ sort: event.target.value, page: "0" })}
        >
          <option value="new">最新入库</option>
          <option value="price">价格从低到高</option>
          <option value="match">条件匹配优先</option>
          <option value="ai">报告候选优先</option>
        </select></div>
        <div className="sp-view-switch" role="group" aria-label="商品视图"><button aria-pressed={display === "table"} onClick={() => setDisplay("table")}>
          表格
        </button>
        <button aria-pressed={grid} onClick={() => setDisplay("cards")}>
          卡片
        </button>
        <button aria-pressed={display === "market"} onClick={() => setDisplay("market")}><ArrowUpRight size={14}/>行情分析</button></div>
        {display !== "market" ? <details ref={fieldPicker} className="ux2-field-picker"><summary>字段显隐</summary><fieldset aria-label="显示字段">{optionalProductColumns.map(([key,name])=><label key={key}><input type="checkbox" checked={show(key)} onChange={()=>toggleColumn(key)}/>{name}</label>)}<div><button onClick={()=>update({columns:optionalProductColumns.map(c=>c[0]).join(',')})}>显示全部</button><button onClick={()=>update({columns:'match'})}>恢复默认</button></div></fieldset></details> : null}

      </div>
      {display!=='market'?<div className="ux2-browser-meta"><span>{rows.length} 件匹配{visible.length?` · 本页 ${page*40+1}–${page*40+visible.length}`:''}{sort!=='new'?` · ${{price:'价格从低到高',match:'条件匹配优先',ai:'报告候选优先'}[sort]}`:''}</span><div><button disabled={!visible.length} onClick={()=>setSelected([...new Set([...selected,...visible.map(c=>c.listing_id)])])}>选择当前页</button>{search||filter!=='all'||params.get('match')&&params.get('match')!=='all'||params.get('ai')&&params.get('ai')!=='all'?<button onClick={()=>update({q:'',state:'all',match:'all',ai:'all',page:'0'})}>清除筛选</button>:null}</div></div>:null}
      {display==='table'&&rows.length?<p className="ux2-table-hint">左右滑动表格，查看价格、研究状态与操作。</p>:null}
      {selected.length && display !== "market" ? (
        <div className="sp-bulk">
          <strong>已选择 {selected.length} 件</strong>{" "}
          <button onClick={() => setSelected([])}>取消选择</button>
          <button disabled={selected.length > 20||selectedMissing} onClick={() => agent.open(productAgentScope(data, params, selected))}>AI 分析选中商品</button>
          <button disabled={selected.length<2||selected.length>4||selectedMissing} onClick={compareSelected}><Columns3 size={14}/>比较所选</button>
          {selectedMissing?<small role="status">部分已选商品资料不可用，请重新选择。</small>:null}
          {selected.length > 20 ? <small>最多20件，请减少选择。</small> : null}
        </div>
      ) : null}
      {display === "market" ? <MarketAnalysis key={`${data.project.id}:${params.get("marketFor") ?? "project"}`} data={data} rows={rows} select={select} /> : !rows.length ? (
        <Panel>
          <h2>{data.total?'没有匹配的商品':'还没有收录商品'}</h2>
          <p>{data.total?'试试调整筛选条件，已有商品仍然保留。':'设置监控计划后，收集到的商品会出现在这里。'}</p>
          {data.total?<button onClick={()=>update({q:'',state:'all',match:'all',ai:'all',page:'0'})}>清除筛选</button>:<button onClick={()=>navigate(contextual(`/projects/${data.project.id}?view=monitors`))}>查看监控计划</button>}
        </Panel>
      ) : grid ? (
        <div className="sp-products-grid">
          {visible.map((card) => (
            <Panel key={card.listing_id}>
              <label>
                <input
                  type="checkbox"
                  aria-label={`选择 ${card.title}`}
                  checked={selected.includes(card.listing_id)}
                  onChange={() => toggle(card.listing_id)}
                />
                选择商品
              </label>
              <button
                className="sp-card-image"
                aria-label={`查看 ${card.title} 的图片与详情`}
                onClick={() => select(card.listing_id)}
              >
                <ProductThumbnail card={card} large />
              </button>
              <button
                className="sp-title-button"
                title={card.title}
                onClick={() => select(card.listing_id)}
              >
                {card.title}
              </button>
              <h2>{price(card)}</h2>
              <p>
                {card.location ?? "地区未知"} · {card.seller_name ?? "卖家未知"}
              </p>
              {fields ? <ConditionCell insight={insights.items.get(card.listing_id)!} /> : null}
              {show('condition')?<p>成色声明：{card.search_condition??'未知'}</p>:null}
              {show('repair')?<p>维修等情况需在商品证据中核实</p>:null}
              {show('source')?<p>采集来源：{card.source_run_ids.map(id=>`#${id}`).join(', ')||'待确认'}</p>:null}
              <ResearchCell card={card} insight={insights.items.get(card.listing_id)!} compact />
              <div className="ux2-product-actions"><button onClick={()=>select(card.listing_id)}>查看详情 <ArrowUpRight size={13}/></button><button disabled={busy} aria-label={`${data.favorites.includes(card.listing_id)?'取消收藏':'收藏'}商品 #${card.listing_id}`} onClick={()=>void favorite(card.listing_id)}><Bookmark size={14} fill={data.favorites.includes(card.listing_id)?'currentColor':'none'}/>{data.favorites.includes(card.listing_id)?'已收藏':'收藏'}</button></div>
            </Panel>
          ))}
        </div>
      ) : (
        <div className="sp-table-wrap">
          <table className="sp-table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="全选当前页"
                    ref={input=>{if(input)input.indeterminate=visible.some(c=>selected.includes(c.listing_id))&&!visible.every(c=>selected.includes(c.listing_id))}}
                    checked={
                      visible.length > 0 &&
                      visible.every((c) => selected.includes(c.listing_id))
                    }
                    onChange={(event) =>
                      setSelected(
                        event.target.checked
                          ? [
                              ...new Set([
                                ...selected,
                                ...visible.map((c) => c.listing_id),
                              ]),
                            ]
                          : selected.filter(
                              (id) => !visible.some((c) => c.listing_id === id),
                            ),
                      )
                    }
                  />
                </th>
                <th>商品信息</th>
                <th>挂牌价格</th>
                {fields ? <th aria-sort={sort === "match" ? "ascending" : undefined}><button className="sp-column-sort" title="按初步符合、待核实、尚未判断、明确不符合排序" onClick={() => update({ sort: "match", page: "0" })}>条件匹配</button></th> : null}
                <th>卖家 / 地区</th>
                <th aria-sort={sort === "ai" ? "descending" : undefined}><button className="sp-column-sort" title="当前报告候选优先；具体判断可单独筛选" onClick={() => update({ sort: "ai", page: "0" })}>AI 判断 / 研究覆盖</button></th>
                {show('condition')?<th>成色声明</th>:null}
                {show('repair')?<th>维修与待核实</th>:null}
                {show('source')?<th>采集来源</th>:null}
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((card) => (
                <tr key={card.listing_id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`选择 ${card.title}`}
                      checked={selected.includes(card.listing_id)}
                      onChange={() => toggle(card.listing_id)}
                    />
                  </td>
                  <td>
                    <button
                      className="sp-product-cell"
                      title={card.title}
                      onClick={() => select(card.listing_id)}
                    >
                      <ProductThumbnail card={card} />
                      <span>
                        <strong>{card.title || "未记录标题"}</strong>
                        <small>闲鱼 · 商品 #{card.listing_id}</small>
                      </span>
                    </button>
                  </td>
                  <td className="sp-price">{price(card)}</td>
                  {fields ? <td><ConditionCell insight={insights.items.get(card.listing_id)!} /></td> : null}
                  <td>
                    {card.seller_name ?? "未知"}
                    <small>{card.location ?? "地区未知"}</small>
                  </td>
                  <td>
                    <ResearchCell card={card} insight={insights.items.get(card.listing_id)!} compact />
                  </td>
                  {show('condition')?<td>{card.search_condition??'未知'}</td>:null}
                  {show('repair')?<td><button onClick={()=>select(card.listing_id)}>查看证据</button></td>:null}
                  {show('source')?<td>{card.source_run_ids.map(id=>`#${id}`).join(', ')||'来源待确认'}</td>:null}
                  <td><div className="ux2-product-actions"><button onClick={()=>select(card.listing_id)} aria-label={`查看商品 #${card.listing_id} 详情`}>详情</button><button disabled={busy} aria-label={`${data.favorites.includes(card.listing_id)?'取消收藏':'收藏'}商品 #${card.listing_id}`} onClick={()=>void favorite(card.listing_id)}><Bookmark size={14} fill={data.favorites.includes(card.listing_id)?'currentColor':'none'}/></button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {display !== "market" ? <div className="sp-pagination" role="navigation" aria-label="商品分页">
        <span aria-live="polite">共 {rows.length} 件 · 每页 40 件 · 第 {pageCount ? page + 1 : 0} / {pageCount} 页</span>
        <button disabled={page === 0} onClick={() => update({ page: String(page - 1) })}>
          上一页
        </button>
        <button
          disabled={(page + 1) * 40 >= rows.length}
          onClick={() => update({ page: String(page + 1) })}
        >
          下一页
        </button>
      </div> : null}
      <details className="sp-secondary-details sp-disclosure"><summary>证据变化与待复评</summary><EvidenceChanges data={data} compact /></details>
      <AutoCoverCache taskId={data.project.id}/>
    </div>
  );
}
