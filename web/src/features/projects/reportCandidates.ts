import type { ProjectOverview } from "../../api/projectClient";

export function candidateIds(data: ProjectOverview) {
  try {
    const ids: unknown = JSON.parse(data.report?.candidate_ids_json ?? "[]");
    return Array.isArray(ids) ? [...new Set(ids.filter((id): id is number => Number.isSafeInteger(id) && data.cards.some(card => card.listing_id === id)))] : [];
  } catch { return []; }
}
