import type { VisualView } from "./VisualEvidence";
export type VisualObservation = VisualView["observations"][number];
export const highImpact = new Set(["identity", "device_count", "packaging_print", "function", "authenticity", "repair"]);
export function validObservations(data: VisualView, taskId: number, listingId?: number) {
  if(data.task_id!==taskId || listingId!==undefined && data.listing_id!==listingId)return [];
  const seen=new Set<string>();
  return data.observations.filter(o=>{
    const valid=o.listing_id===data.listing_id && o.independently_verified===false && o.freshness!=="invalid" &&
      (o.origin===undefined || o.origin==="pixels") && (o.source_type===undefined || o.source_type==="image_observation") &&
      typeof o.id==="string" && o.id.startsWith(`visual:${data.listing_id}:${o.study_id}:`) &&
      typeof o.sha256==="string" && /^[a-f0-9]{64}$/.test(o.sha256) && typeof o.run_id==="string" && /^\d+$/.test(o.run_id) &&
      typeof o.visible_content==="string" && typeof o.uncertainty==="string" && typeof o.limited_inference==="string" &&
      ["visible","unreadable","not_shown"].includes(o.status) && ["accepted","pending_review","historical","not_accepted"].includes(o.review_state) &&
      data.images.some(i=>i.media_id===o.media_id && i.sha256===o.sha256);
    if(!valid || seen.has(o.id))return false;seen.add(o.id);return true;
  });
}
export function currentObservation(o: VisualObservation) { return o.freshness==="fresh" && o.review_state==="accepted"; }
export function comparisonObservations(rows: VisualObservation[]) {
  // Missing topic is not proof of safe comparability. Count, identity and packaging never become comparison facts.
  return rows.filter(o=>currentObservation(o) && o.status==="visible" && ["surface","accessory","label"].includes(o.subject??""));
}
export function importantObservations(rows: VisualObservation[]) {
  return rows.filter(o=>currentObservation(o) && o.status==="visible" && !highImpact.has(o.subject??"") && (!!o.references?.length || !!o.affects_criteria?.length));
}
