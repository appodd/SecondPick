import { useQueries } from "@tanstack/react-query";

import { queries } from "../../api/queries";
import type { ListingEvidence } from "../../api/types";
import { EvidenceStatus } from "../inspector/EvidenceStatus";
import { useComparisonSelection } from "./useComparisonSelection";

function attributes(evidence: ListingEvidence) {
  const entries = Object.entries(evidence.detail?.attributes ?? {});
  return entries.length > 0
    ? entries.map(([key, value]) => `${key}: ${value}`).join("；")
    : "未记录";
}

function sellerSources(evidence: ListingEvidence) {
  const entries = Object.entries(evidence.seller_fields.field_sources);
  return entries.length > 0
    ? entries.map(([key, value]) => `${key}: ${value}`).join("；")
    : evidence.seller_fields.data_source;
}

function unresolvedClaims(evidence: ListingEvidence) {
  const claims = [
    evidence.detail && !evidence.detail.independently_verified
      ? "详情属性未独立验证"
      : null,
    !evidence.seller_fields.independently_verified
      ? "卖家字段未独立验证"
      : null,
    evidence.evidence_conflicts.length > 0
      ? `${evidence.evidence_conflicts.length} 项证据冲突`
      : null,
  ].filter(Boolean);
  return claims.length > 0 ? claims.join("、") : "无";
}

function marketMedianRatio(
  evidence: ListingEvidence,
  marketMedian: number | null | undefined,
) {
  if (evidence.price_value === null || !marketMedian || marketMedian <= 0) {
    return "未计算";
  }

  return `${(evidence.price_value / marketMedian).toFixed(2)}×`;
}

export function ComparisonView({
  marketMedian,
  taskId,
}: {
  marketMedian?: number | null;
  taskId: number;
}) {
  const comparison = useComparisonSelection(taskId);
  const results = useQueries({
    queries: comparison.selectedIds.map((listingId) =>
      queries.listingEvidence(taskId, listingId),
    ),
  });

  if (comparison.selectedIds.length < 2) {
    return (
      <div className="comparison-empty">
        <p>至少选择 2 个候选后才能对比，最多可选 4 个。</p>
        <p className="muted">请在“全部候选”中勾选需要对比的商品。</p>
      </div>
    );
  }

  if (results.some((result) => result.isLoading)) {
    return <p className="muted">加载对比证据...</p>;
  }

  const failed = results.find((result) => result.isError);
  if (failed) {
    return <p className="scoped-error" role="status">{failed.error.message}</p>;
  }

  const evidence = results
    .map((result) => result.data)
    .filter((item): item is ListingEvidence => item !== undefined);
  const rows: Array<[string, (item: ListingEvidence) => React.ReactNode]> = [
    ["价格", (item) => item.price_text ?? "未记录"],
    ["市场中位价比例", (item) => marketMedianRatio(item, marketMedian)],
    ["地点", (item) => item.location ?? "未记录"],
    ["成色", (item) => item.search_condition ?? "未记录"],
    ["属性", attributes],
    ["详情状态", (item) => <EvidenceStatus status={item.detail_status} />],
    ["卖家字段来源", sellerSources],
    ["证据冲突", (item) => String(item.evidence_conflicts.length)],
    ["已下载图片", (item) => String(item.collection_state.listing_lifetime_downloaded_product_image_count)],
    ["OCR 数量", (item) => String(item.collection_state.listing_lifetime_ocr_result_count)],
    ["未解决声明", unresolvedClaims],
  ];

  return (
    <div className="data-table-scroll">
      <table className="data-table comparison-table">
        <thead>
          <tr>
            <th scope="col">字段</th>
            {evidence.map((item) => (
              <th key={item.listing_id} scope="col">
                <span>{item.title}</span>
                <button onClick={() => comparison.remove(item.listing_id)} type="button">
                  移出对比
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, renderValue]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              {evidence.map((item) => <td key={item.listing_id}>{renderValue(item)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
