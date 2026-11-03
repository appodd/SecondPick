import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MarketOverview as MarketOverviewData } from "../../api/types";
import { MarketOverview } from "./MarketOverview";

const market = {
  goal: "Find a laptop",
  target_city: "上海",
  run_ids: [1, 2],
  decision_owner: "llm",
  is_final_recommendation: false,
  source_scope: "local_candidate_pool_only",
  price_evidence_level: {
    level: "local",
    label: "本地在售样本",
    sample_count: 3,
    model_use: "context only",
    limitations: ["仅含本地已保存样本"],
  },
  notes: ["不是购买结论"],
  sample_policy: {
    included: "saved candidates",
    excluded_noise_signal_keys: [],
    priced_candidate_count: 3,
    unpriced_candidate_count: 0,
    excluded_noise_sample_count: 0,
    exclusion_summary: [],
  },
  overall: {
    candidate_count: 3,
    priced_candidate_count: 3,
    priced_clean_sample_count: 3,
    priced_excluded_noise_sample_count: 0,
    source_quality: "local",
    price_evidence_level: {
      level: "local",
      label: "本地在售样本",
      sample_count: 3,
      model_use: "context only",
      limitations: [],
    },
    price_summary: {
      count: 3,
      min: 5000,
      q1: 5500,
      median: 6000,
      q3: 7000,
      max: 8000,
      spread: 3000,
      values: [5000, 6000, 8000],
    },
  },
  spec_price_groups: [],
  near_duplicate_groups: [],
  suggested_llm_checks: [],
  geography: {
    locations: [
      { value: "上海", count: 2 },
      { value: "杭州", count: 1 },
    ],
    target_city_count: 2,
    target_city_coverage_ratio: 0.6667,
  },
  collection_coverage: {
    collection_rounds: 2,
    listing_snapshot_count: 5,
    duplicate_count: 2,
    duplicate_rate: 0.4,
    captured_detail_count: 1,
    blocked_detail_count: 1,
    not_captured_detail_count: 1,
    detail_coverage_ratio: 0.3333,
  },
  search_coverage: {
    status: "collecting",
    unique_candidates: 3,
    target_min: 20,
    target_max: 80,
    marginal_gain_threshold: 0.1,
    low_gain_streak: 0,
    suggested_action: "continue_search",
    runs: [
      {
        run_id: 1,
        source_queries: ["laptop"],
        unique_in_run: 2,
        new_unique_count: 2,
        cumulative_unique_count: 2,
        new_unique_ratio: null,
      },
      {
        run_id: 2,
        source_queries: ["laptop local"],
        unique_in_run: 3,
        new_unique_count: 1,
        cumulative_unique_count: 3,
        new_unique_ratio: 0.5,
      },
    ],
  },
} as unknown as MarketOverviewData;

describe("MarketOverview", () => {
  it("shows quartiles, geography, run yield, collection coverage, and stop state", () => {
    render(<MarketOverview market={market} />);

    expect(screen.getByText("下四分位").nextElementSibling).toHaveTextContent("¥5,500");
    expect(screen.getByText("上四分位").nextElementSibling).toHaveTextContent("¥7,000");

    const geography = screen.getByRole("table", { name: "地区分布数据" });
    expect(within(geography).getByRole("row", { name: "上海 2" })).toBeInTheDocument();
    expect(screen.getByText("目标地区覆盖 2 / 3（66.7%）")).toBeInTheDocument();

    const yieldTable = screen.getByRole("table", { name: "每轮新增候选" });
    expect(within(yieldTable).getByRole("row", { name: /Run #2.*1.*3.*50.0%/ }))
      .toBeInTheDocument();

    expect(screen.getByText("采集轮次").nextElementSibling).toHaveTextContent("2");
    expect(screen.getByText("重复率").nextElementSibling).toHaveTextContent("40.0%");
    expect(screen.getByText("详情覆盖").nextElementSibling).toHaveTextContent("1 / 3（33.3%）");
    expect(screen.getByText("停止条件").nextElementSibling)
      .toHaveTextContent("collecting · continue_search");
  });
});
