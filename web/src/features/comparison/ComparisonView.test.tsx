import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ListingEvidence } from "../../api/types";
import { ComparisonView } from "./ComparisonView";

function evidence({
  detailVerified,
  listingId,
  ocrCount,
  sellerVerified,
  withConflict,
}: {
  detailVerified: boolean;
  listingId: number;
  ocrCount: number;
  sellerVerified: boolean;
  withConflict: boolean;
}): ListingEvidence {
  return {
    listing_id: listingId,
    source_run_ids: [1],
    url: `https://example.test/${listingId}`,
    title: `Candidate ${listingId}`,
    search_description: null,
    search_description_status: "missing",
    price_text: "6800",
    price_value: 6800,
    location: "上海",
    seller_name: "Seller A",
    search_condition: "九成新",
    has_detail: true,
    detail_status: "captured",
    detail: {
      snapshot_id: listingId,
      run_id: 1,
      description: "自用机器",
      attributes: { 内存: "16GB" },
      attributes_source: "seller_entered_attribute",
      evidence_source: "seller_entered_attribute",
      independently_verified: detailVerified,
    },
    seller_fields: {
      seller_credit_level: "优秀",
      seller_registered_days: 900,
      seller_sold_count: 12,
      seller_good_rate: "98%",
      seller_realname_verified: true,
      seller_reply_rate_24h: "95%",
      data_source: "db",
      field_sources: { seller_credit_level: "db" },
      source: "platform_seller_field",
      independently_verified: sellerVerified,
    },
    seller_other_items: [],
    evidence_conflicts: withConflict
      ? [
          {
            field: "内存",
            selected_value: "16GB",
            selected_source: "seller_entered_attribute",
            conflicting_value: "8GB",
            conflicting_source: "detail_dom_fallback",
          },
        ]
      : [],
    collection_state: {
      detail_snapshot_count: 1,
      valid_detail_snapshot_count: 1,
      blocked_detail_snapshot_count: 0,
      listing_lifetime_product_image_count: 4,
      listing_lifetime_downloaded_product_image_count: 3,
      listing_lifetime_ocr_result_count: ocrCount,
    },
    raw_text_excerpt: null,
  };
}

describe("ComparisonView", () => {
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("summarizes unverified claims and conflicts without treating missing OCR as a claim", async () => {
    sessionStorage.setItem("workbench.comparison.8", JSON.stringify([101, 102]));
    const evidenceById = new Map([
      [
        101,
        evidence({
          detailVerified: false,
          listingId: 101,
          ocrCount: 2,
          sellerVerified: false,
          withConflict: true,
        }),
      ],
      [
        102,
        evidence({
          detailVerified: true,
          listingId: 102,
          ocrCount: 0,
          sellerVerified: true,
          withConflict: false,
        }),
      ],
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(input.toString(), window.location.origin);
        const listingId = Number(url.pathname.split("/")[3]);
        return new Response(JSON.stringify(evidenceById.get(listingId)), {
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ComparisonView taskId={8} marketMedian={6200} />
      </QueryClientProvider>,
    );

    const row = await screen.findByRole("row", { name: /未解决声明/ });
    const cells = within(row).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent(
      "详情属性未独立验证、卖家字段未独立验证、1 项证据冲突",
    );
    expect(cells[1]).toHaveTextContent(/^无$/);
    const ratioRow = screen.getByRole("row", { name: /市场中位价比例/ });
    expect(within(ratioRow).getAllByRole("cell")[0]).toHaveTextContent("1.10×");
  });
});
