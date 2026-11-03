import type { CandidatePage } from "../../api/types";
import { useComparisonSelection } from "../comparison/useComparisonSelection";
import { EvidenceStatus } from "../inspector/EvidenceStatus";
import {
  type CandidateSort,
  useCandidateFilters,
} from "./useCandidateFilters";

export interface CandidateTableProps {
  candidatePage: CandidatePage;
  isLoadingMore?: boolean;
  onLoadMore?: (cursor: string) => void;
  onSelectListing: (listingId: number) => void;
  selectedListingId?: number;
  taskId: number;
}

export function CandidateTable({
  candidatePage,
  isLoadingMore = false,
  onLoadMore,
  onSelectListing,
  selectedListingId,
  taskId,
}: CandidateTableProps) {
  const {
    condition,
    conditions,
    evidenceStatus,
    filteredCandidates,
    listingQuery,
    location,
    locations,
    maximumPrice,
    minimumPrice,
    query,
    setCondition,
    setEvidenceStatus,
    setListingQuery,
    setLocation,
    setMaximumPrice,
    setMinimumPrice,
    setQuery,
    setSort,
    sort,
  } = useCandidateFilters(candidatePage.candidates);
  const comparison = useComparisonSelection(taskId);

  return (
    <section className="candidate-table-view" aria-label="候选列表">
      <div className="candidate-table-toolbar">
        <label className="candidate-filter-control candidate-filter-control--wide">
          <span>筛选当前已加载候选</span>
          <input
            aria-label="筛选候选"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="标题、地点、成色或卖家"
            type="search"
            value={query}
          />
        </label>
        <div className="candidate-counts" aria-label="候选计数">
          <span>已返回 {candidatePage.returned_count} 条</span>
          <span>去重候选 {candidatePage.deduplicated_count} 条</span>
        </div>
      </div>

      <div className="candidate-filter-grid" aria-label="候选筛选和排序">
        <label className="candidate-filter-control candidate-filter-control--wide">
          <span>标题或 listing ID</span>
          <input
            aria-label="搜索标题或 listing ID"
            onChange={(event) => setListingQuery(event.target.value)}
            placeholder="输入标题或 listing ID"
            type="search"
            value={listingQuery}
          />
        </label>
        <label className="candidate-filter-control">
          <span>地区</span>
          <select
            aria-label="地区"
            onChange={(event) => setLocation(event.target.value)}
            value={location}
          >
            <option value="">全部地区</option>
            {locations.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="candidate-filter-control">
          <span>成色</span>
          <select
            aria-label="成色"
            onChange={(event) => setCondition(event.target.value)}
            value={condition}
          >
            <option value="">全部成色</option>
            {conditions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="candidate-filter-control">
          <span>证据状态</span>
          <select
            aria-label="证据状态"
            onChange={(event) => setEvidenceStatus(event.target.value)}
            value={evidenceStatus}
          >
            <option value="">全部状态</option>
            <option value="captured">已保存</option>
            <option value="blocked">访问被阻断</option>
            <option value="not_captured">未采集</option>
          </select>
        </label>
        <label className="candidate-filter-control">
          <span>最低价格</span>
          <input
            aria-label="最低价格"
            min="0"
            onChange={(event) => setMinimumPrice(event.target.value)}
            step="any"
            type="number"
            value={minimumPrice}
          />
        </label>
        <label className="candidate-filter-control">
          <span>最高价格</span>
          <input
            aria-label="最高价格"
            min="0"
            onChange={(event) => setMaximumPrice(event.target.value)}
            step="any"
            type="number"
            value={maximumPrice}
          />
        </label>
        <label className="candidate-filter-control">
          <span>排序</span>
          <select
            aria-label="排序"
            onChange={(event) => setSort(event.target.value as CandidateSort)}
            value={sort}
          >
            <option value="default">默认顺序</option>
            <option value="price_asc">价格从低到高</option>
            <option value="price_desc">价格从高到低</option>
            <option value="listing_id_asc">listing ID 从小到大</option>
            <option value="listing_id_desc">listing ID 从大到小</option>
          </select>
        </label>
      </div>

      {comparison.error ? (
        <p className="scoped-error" role="status">
          {comparison.error}
        </p>
      ) : null}

      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">对比</th>
              <th scope="col">标题</th>
              <th scope="col">价格</th>
              <th scope="col">地点</th>
              <th scope="col">成色</th>
              <th scope="col">详情状态</th>
              <th scope="col">来源运行</th>
            </tr>
          </thead>
          <tbody>
            {filteredCandidates.map((candidate) => (
              <tr
                className={
                  candidate.listing_id === selectedListingId
                    ? "data-table__selected"
                    : undefined
                }
                key={candidate.listing_id}
              >
                <td>
                  <input
                    aria-label={`选择 ${candidate.title} 进行对比`}
                    checked={comparison.selectedIds.includes(candidate.listing_id)}
                    onChange={() => comparison.toggle(candidate.listing_id)}
                    type="checkbox"
                  />
                </td>
                <td>
                  <button
                    className="candidate-title-button"
                    onClick={() => onSelectListing(candidate.listing_id)}
                    type="button"
                  >
                    {candidate.title}
                  </button>
                  <div className="muted">商品 #{candidate.listing_id}</div>
                </td>
                <td>{candidate.price_text ?? "未记录"}</td>
                <td>{candidate.location ?? "未记录"}</td>
                <td>{candidate.search_condition ?? "未记录"}</td>
                <td>
                  <EvidenceStatus status={candidate.detail_status} />
                </td>
                <td>{candidate.source_run_ids.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filteredCandidates.length === 0 ? (
        <p className="muted">当前已加载候选中没有匹配项。</p>
      ) : null}
      {candidatePage.page.has_more && candidatePage.page.next_cursor && onLoadMore ? (
        <button
          className="load-more-button"
          disabled={isLoadingMore}
          onClick={() => onLoadMore(candidatePage.page.next_cursor as string)}
          type="button"
        >
          {isLoadingMore ? "加载中..." : "加载更多"}
        </button>
      ) : null}
    </section>
  );
}
