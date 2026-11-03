import { useState } from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import type { CandidatePage, CandidateSummary } from "../../api/types";
import { CandidateTable } from "./CandidateTable";

const candidates: CandidateSummary[] = [
  candidate(101, "ThinkPad X1 Carbon", "6800", "上海", "九成新", [1, 2]),
  candidate(102, "MacBook Air M2", "5900", "杭州", "轻微使用", [2]),
  candidate(103, "Surface Laptop 5", "5200", "上海", null, [3]),
  candidate(104, "Dell XPS 13", "4800", "南京", "八成新", [4]),
  candidate(105, "HP EliteBook", "4300", "苏州", "正常使用", [5]),
];

function candidate(
  listingId: number,
  title: string,
  priceText: string,
  location: string,
  condition: string | null,
  sourceRunIds: number[],
): CandidateSummary {
  return {
    listing_id: listingId,
    source_run_ids: sourceRunIds,
    url: `https://example.test/${listingId}`,
    title,
    search_description: null,
    search_description_status: "missing",
    price_text: priceText,
    price_value: Number(priceText),
    location,
    seller_name: `Seller ${listingId}`,
    search_condition: condition,
    has_detail: listingId === 101,
    detail_status:
      listingId === 101 ? "captured" : listingId === 102 ? "blocked" : "not_captured",
  };
}

function page(rows: CandidateSummary[], hasMore: boolean): CandidatePage {
  return {
    scope: { task_id: 8, run_ids: [1, 2, 3, 4, 5] },
    scope_revision: "fixture",
    field_semantics: {
      search_description: "搜索结果描述",
      search_description_status: {
        missing: "缺失",
        redundant_with_title: "与标题重复",
        distinct: "独立描述",
      },
    },
    deduplicated_count: 18,
    returned_count: rows.length,
    page: {
      offset: 0,
      limit: 4,
      has_more: hasMore,
      next_cursor: hasMore ? "next-page" : null,
    },
    candidates: rows,
  };
}

function CursorHarness() {
  const [candidatePage, setCandidatePage] = useState(page(candidates.slice(0, 2), true));

  return (
    <CandidateTable
      candidatePage={candidatePage}
      onLoadMore={() => setCandidatePage(page(candidates.slice(0, 3), false))}
      onSelectListing={() => undefined}
      taskId={8}
    />
  );
}

describe("CandidateTable", () => {
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
  });

  it("filters only loaded candidates and appends the next cursor page", async () => {
    const user = userEvent.setup();
    render(<CursorHarness />);

    expect(screen.getByText("已返回 2 条")).toBeInTheDocument();
    expect(screen.getByText("去重候选 18 条")).toBeInTheDocument();
    expect(screen.getByText("筛选当前已加载候选")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "筛选候选" }), "上海");
    expect(screen.getByRole("button", { name: "ThinkPad X1 Carbon" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "MacBook Air M2" })).not.toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox", { name: "筛选候选" }));
    await user.click(screen.getByRole("button", { name: "加载更多" }));
    expect(screen.getByRole("button", { name: "Surface Laptop 5" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "加载更多" })).not.toBeInTheDocument();
  });

  it("searches listing IDs and applies deterministic filters and sorting", async () => {
    const user = userEvent.setup();
    render(
      <CandidateTable
        candidatePage={page(candidates, false)}
        onSelectListing={() => undefined}
        taskId={8}
      />,
    );

    const search = screen.getByRole("searchbox", { name: "搜索标题或 listing ID" });
    await user.type(search, "102");
    expect(screen.getByRole("button", { name: "MacBook Air M2" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ThinkPad X1 Carbon" }))
      .not.toBeInTheDocument();

    await user.clear(search);
    await user.selectOptions(screen.getByRole("combobox", { name: "地区" }), "上海");
    await user.selectOptions(screen.getByRole("combobox", { name: "成色" }), "九成新");
    expect(screen.getByRole("button", { name: "ThinkPad X1 Carbon" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Surface Laptop 5" }))
      .not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "地区" }), "");
    await user.selectOptions(screen.getByRole("combobox", { name: "成色" }), "");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "证据状态" }),
      "blocked",
    );
    expect(screen.getByRole("button", { name: "MacBook Air M2" })).toBeInTheDocument();
    expect(screen.getByText("详情访问被阻断")).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "证据状态" }), "");
    await user.type(screen.getByRole("spinbutton", { name: "最低价格" }), "5000");
    await user.type(screen.getByRole("spinbutton", { name: "最高价格" }), "6000");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "排序" }),
      "price_asc",
    );
    const titleButtons = within(screen.getByRole("table"))
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(titleButtons).toEqual(["Surface Laptop 5", "MacBook Air M2"]);
  });

  it("stores at most four comparison selections per task", async () => {
    const user = userEvent.setup();
    render(
      <CandidateTable
        candidatePage={page(candidates, false)}
        onSelectListing={() => undefined}
        taskId={8}
      />,
    );

    for (const listing of candidates.slice(0, 4)) {
      await user.click(
        screen.getByRole("checkbox", { name: `选择 ${listing.title} 进行对比` }),
      );
    }
    await user.click(
      screen.getByRole("checkbox", { name: "选择 HP EliteBook 进行对比" }),
    );

    expect(screen.getByRole("status")).toHaveTextContent("每个任务最多对比 4 个候选");
    expect(
      screen.getByRole("checkbox", { name: "选择 HP EliteBook 进行对比" }),
    ).not.toBeChecked();
    expect(sessionStorage.getItem("workbench.comparison.8")).toBe(
      JSON.stringify([101, 102, 103, 104]),
    );
  });
});
