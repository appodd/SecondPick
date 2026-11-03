import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ListingEvidence } from "../../api/types";
import { EvidenceStatus } from "./EvidenceStatus";
import { ListingEvidencePanel } from "./ListingEvidencePanel";

const sellerClaimFixture: ListingEvidence = {
  listing_id: 101,
  source_run_ids: [1, 2],
  url: "https://example.test/101",
  title: "ThinkPad X1 Carbon",
  search_description: null,
  search_description_status: "missing",
  price_text: "6800",
  price_value: 6800,
  location: "上海",
  seller_name: "Seller A",
  search_condition: null,
  has_detail: true,
  detail_status: "captured",
  detail: {
    snapshot_id: 31,
    run_id: 2,
    description: "自用机器，外观良好",
    attributes: { 内存: "16GB" },
    attributes_source: "seller_entered_attribute",
    evidence_source: "detail_snapshot",
    independently_verified: false,
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
    independently_verified: false,
  },
  seller_other_items: [],
  evidence_conflicts: [],
  collection_state: {
    detail_snapshot_count: 1,
    valid_detail_snapshot_count: 1,
    blocked_detail_snapshot_count: 0,
    listing_lifetime_product_image_count: 4,
    listing_lifetime_downloaded_product_image_count: 3,
    listing_lifetime_ocr_result_count: 0,
  },
  raw_text_excerpt: "自用机器",
};

describe("ListingEvidencePanel", () => {
  afterEach(cleanup);

  it.each([
    ["not_captured", "尚未采集详情"],
    ["blocked", "详情访问被阻断"],
    ["captured", "详情已保存"],
  ] as const)("renders %s distinctly", (status, label) => {
    render(<EvidenceStatus status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("labels seller-entered attributes as unverified", () => {
    render(<ListingEvidencePanel evidence={sellerClaimFixture} />);
    expect(screen.getByText(/以上为已保存的平台展示，未独立核实/)).toBeInTheDocument();
    expect(screen.getByText(/详情属性未独立验证/)).toBeInTheDocument();
  });
  it("keeps conflicting relayed statements visible with provenance and escaped text", () => {
    render(<ListingEvidencePanel evidence={{ ...sellerClaimFixture, user_statements: [
      { id: 1, source_message_id: 11, kind: "seller_reply", statement_text: "<script>没换屏</script>", independently_verified: false, created_at: "fixture" },
      { id: 2, source_message_id: 12, kind: "seller_reply", statement_text: "后来称换过屏", independently_verified: false, created_at: "fixture" },
    ], user_statement_count: 21, user_statements_truncated: true }} />);
    expect(screen.getByText("<script>没换屏</script>")).toBeVisible();
    expect(screen.getByText("商品 #101")).toBeVisible();
    expect(screen.getByText("后来称换过屏")).toBeVisible();
    expect(screen.getAllByText("用户转述卖家答复")).toHaveLength(2);
    expect(screen.getByText(/由用户提供，未经独立核实/)).toBeVisible();
    expect(screen.getByText(/仅展示最近 20 条/)).toBeVisible();
  });

  it("suggests questions only for missing evidence categories", () => {
    render(<ListingEvidencePanel evidence={sellerClaimFixture} />);

    expect(screen.getByText("向卖家确认成色与瑕疵")).toBeInTheDocument();
    expect(screen.queryByText("向卖家索取可核验的图片或文字信息")).not.toBeInTheDocument();
    expect(screen.queryByText(/内存是否为 16GB/)).not.toBeInTheDocument();
  });
});
