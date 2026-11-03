import type {
  MarketOverview as MarketOverviewData,
  PriceEvidenceLevel,
  PriceSummary,
} from "../../api/types";

function currency(value: number | null) {
  return value === null ? "未记录" : `¥${value.toLocaleString("zh-CN")}`;
}

function percentage(value: number | null) {
  return value === null ? "未计算" : `${(value * 100).toFixed(1)}%`;
}

function PriceSummaryBlock({
  evidence,
  summary,
  title,
}: {
  evidence: PriceEvidenceLevel;
  summary: PriceSummary;
  title: string;
}) {
  return (
    <section className="price-summary">
      <div className="price-summary__heading">
        <h3>{title}</h3>
        <span>{summary.count} 个样本 · {evidence.label}</span>
      </div>
      <dl className="price-summary__facts">
        <div><dt>最低</dt><dd>{currency(summary.min)}</dd></div>
        <div><dt>下四分位</dt><dd>{currency(summary.q1)}</dd></div>
        <div><dt>中位数</dt><dd>{currency(summary.median)}</dd></div>
        <div><dt>上四分位</dt><dd>{currency(summary.q3)}</dd></div>
        <div><dt>最高</dt><dd>{currency(summary.max)}</dd></div>
      </dl>
    </section>
  );
}

function PriceDistribution({ values }: { values: number[] }) {
  const counts = Array.from(
    values.reduce((map, value) => map.set(value, (map.get(value) ?? 0) + 1), new Map<number, number>()),
  ).sort(([left], [right]) => left - right);
  const maximum = Math.max(1, ...counts.map(([, count]) => count));

  return (
    <section className="market-distribution" aria-labelledby="price-distribution-title">
      <h3 id="price-distribution-title">价格分布</h3>
      <div className="html-bars" aria-hidden="true">
        {counts.map(([value, count]) => (
          <div className="html-bar-row" key={value}>
            <span>{currency(value)}</span>
            <div className="html-bar-track">
              <span className="html-bar-fill" style={{ width: `${(count / maximum) * 100}%` }} />
            </div>
            <strong>{count}</strong>
          </div>
        ))}
      </div>
      <table className="accessible-data-table">
        <caption>价格分布数据</caption>
        <thead><tr><th scope="col">价格</th><th scope="col">数量</th></tr></thead>
        <tbody>
          {counts.map(([value, count]) => (
            <tr key={value}><td>{currency(value)}</td><td>{count}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Geography({ market }: { market: MarketOverviewData }) {
  return (
    <section className="market-section">
      <div className="market-section__heading">
        <h3>地区覆盖</h3>
        <span>
          目标地区覆盖 {market.geography.target_city_count} /{" "}
          {market.overall.candidate_count}（
          {percentage(market.geography.target_city_coverage_ratio)}）
        </span>
      </div>
      <table className="accessible-data-table market-data-table">
        <caption>地区分布数据</caption>
        <thead>
          <tr><th scope="col">地区</th><th scope="col">候选数</th></tr>
        </thead>
        <tbody>
          {market.geography.locations.map((location) => (
            <tr key={location.value}>
              <td>{location.value}</td>
              <td>{location.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function RunYield({ market }: { market: MarketOverviewData }) {
  return (
    <section className="market-section">
      <h3>运行边际收益</h3>
      <div className="data-table-scroll">
        <table className="data-table market-data-table">
          <caption>每轮新增候选</caption>
          <thead>
            <tr>
              <th scope="col">运行</th>
              <th scope="col">查询</th>
              <th scope="col">新增唯一候选</th>
              <th scope="col">累计唯一候选</th>
              <th scope="col">边际收益</th>
            </tr>
          </thead>
          <tbody>
            {market.search_coverage.runs.map((run) => (
              <tr key={run.run_id}>
                <td>Run #{run.run_id}</td>
                <td>{run.source_queries.join("；") || "未记录"}</td>
                <td>{run.new_unique_count}</td>
                <td>{run.cumulative_unique_count}</td>
                <td>{percentage(run.new_unique_ratio)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CollectionCoverage({ market }: { market: MarketOverviewData }) {
  const coverage = market.collection_coverage;
  const detailCandidateCount =
    coverage.captured_detail_count +
    coverage.blocked_detail_count +
    coverage.not_captured_detail_count;

  return (
    <section className="market-section">
      <h3>采集覆盖</h3>
      <dl className="market-facts">
        <div><dt>采集轮次</dt><dd>{coverage.collection_rounds}</dd></div>
        <div>
          <dt>重复率</dt>
          <dd>{percentage(coverage.duplicate_rate)}</dd>
        </div>
        <div>
          <dt>详情覆盖</dt>
          <dd>
            {coverage.captured_detail_count} / {detailCandidateCount}（
            {percentage(coverage.detail_coverage_ratio)}）
          </dd>
        </div>
        <div><dt>详情被阻断</dt><dd>{coverage.blocked_detail_count}</dd></div>
        <div>
          <dt>停止条件</dt>
          <dd>
            {market.search_coverage.status} ·{" "}
            {market.search_coverage.suggested_action}
          </dd>
        </div>
      </dl>
    </section>
  );
}

export function MarketOverview({ market }: { market: MarketOverviewData }) {
  return (
    <div className="market-overview">
      <PriceSummaryBlock
        evidence={market.overall.price_evidence_level}
        summary={market.overall.price_summary}
        title="整体价格"
      />
      <PriceDistribution values={market.overall.price_summary.values} />
      <Geography market={market} />
      <RunYield market={market} />
      <CollectionCoverage market={market} />
      {market.spec_price_groups.map((group) => (
        <PriceSummaryBlock
          evidence={group.price_evidence_level}
          key={group.group_id}
          summary={group.price_summary}
          title={group.spec_tokens.join(" · ") || group.group_id}
        />
      ))}
      <section className="market-notes">
        <h3>证据限制</h3>
        <ul className="compact-list">
          {[...market.price_evidence_level.limitations, ...market.notes].map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
