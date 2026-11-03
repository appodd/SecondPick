import { useMemo, useState } from "react";

import type { CandidateSummary } from "../../api/types";

export type CandidateSort =
  | "default"
  | "price_asc"
  | "price_desc"
  | "listing_id_asc"
  | "listing_id_desc";

function parsePriceBound(value: string): number | null {
  if (!value.trim()) {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function useCandidateFilters(candidates: CandidateSummary[]) {
  const [query, setQuery] = useState("");
  const [listingQuery, setListingQuery] = useState("");
  const [location, setLocation] = useState("");
  const [condition, setCondition] = useState("");
  const [evidenceStatus, setEvidenceStatus] = useState("");
  const [minimumPrice, setMinimumPrice] = useState("");
  const [maximumPrice, setMaximumPrice] = useState("");
  const [sort, setSort] = useState<CandidateSort>("default");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const normalizedListingQuery = listingQuery.trim().toLocaleLowerCase();
  const locations = useMemo(
    () =>
      [...new Set(candidates.flatMap((candidate) => candidate.location ?? []))].sort(
        (left, right) => left.localeCompare(right, "zh-CN"),
      ),
    [candidates],
  );
  const conditions = useMemo(
    () =>
      [
        ...new Set(
          candidates.flatMap((candidate) => candidate.search_condition ?? []),
        ),
      ].sort((left, right) => left.localeCompare(right, "zh-CN")),
    [candidates],
  );
  const filteredCandidates = useMemo(() => {
    const priceFloor = parsePriceBound(minimumPrice);
    const priceCeiling = parsePriceBound(maximumPrice);
    const originalPositions = new Map(
      candidates.map((candidate, index) => [candidate.listing_id, index]),
    );
    const matches = candidates.filter((candidate) => {
      const matchesGeneralQuery =
        !normalizedQuery ||
        [
          candidate.title,
          candidate.price_text,
          candidate.location,
          candidate.search_condition,
          candidate.seller_name,
        ].some((value) => value?.toLocaleLowerCase().includes(normalizedQuery));
      const matchesListingQuery =
        !normalizedListingQuery ||
        candidate.title.toLocaleLowerCase().includes(normalizedListingQuery) ||
        String(candidate.listing_id).includes(normalizedListingQuery);
      const matchesPrice =
        (priceFloor === null ||
          (candidate.price_value !== null && candidate.price_value >= priceFloor)) &&
        (priceCeiling === null ||
          (candidate.price_value !== null && candidate.price_value <= priceCeiling));

      return (
        matchesGeneralQuery &&
        matchesListingQuery &&
        (!location || candidate.location === location) &&
        (!condition || candidate.search_condition === condition) &&
        (!evidenceStatus || candidate.detail_status === evidenceStatus) &&
        matchesPrice
      );
    });

    return matches.sort((left, right) => {
      if (sort === "price_asc" || sort === "price_desc") {
        if (left.price_value === null) {
          return right.price_value === null ? 0 : 1;
        }
        if (right.price_value === null) {
          return -1;
        }
        const direction = sort === "price_asc" ? 1 : -1;
        const priceOrder = (left.price_value - right.price_value) * direction;
        if (priceOrder !== 0) {
          return priceOrder;
        }
      } else if (sort === "listing_id_asc" || sort === "listing_id_desc") {
        const direction = sort === "listing_id_asc" ? 1 : -1;
        const listingOrder = (left.listing_id - right.listing_id) * direction;
        if (listingOrder !== 0) {
          return listingOrder;
        }
      }

      return (
        (originalPositions.get(left.listing_id) ?? 0) -
        (originalPositions.get(right.listing_id) ?? 0)
      );
    });
  }, [
    candidates,
    condition,
    evidenceStatus,
    location,
    maximumPrice,
    minimumPrice,
    normalizedListingQuery,
    normalizedQuery,
    sort,
  ]);

  return {
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
  };
}
