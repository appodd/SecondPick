import { request } from "./client";
export interface Investigation {
  id: number; listing_id: number; goal_revision: number; kind: "detail" | "manual" | "seller_public";
  state: string; outdated: boolean; job_id: number | null; job_state: string | null; stage: string | null; error_code: string | null;
  plan: { title: string; objective: string; reason: string; evidence_gaps: string[]; expected_information: string[];
    capability: string; manual_questions: string[]; seller_public_questions: string[]; source_study_ids: number[] };
  outcome: { new_evidence?: boolean; detail_snapshot_ids?: number[]; manually_reassessed?: boolean; reassessed?: boolean };
}
export interface Investigations { items: Investigation[]; skipped: { listing_id: number; reason: string }[]; automatic_research_held: boolean; max_listings: number }
const base = (project: number) => `/api/projects/${project}/investigations`;
const post = (body?: unknown): RequestInit => ({ method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
export const investigationApi = {
  list: (project: number, listing?: number) => request<Investigations>(`${base(project)}${listing ? `?listing=${listing}` : ""}`),
  plan: (project: number, ids?: number[]) => request<Investigations>(`${base(project)}/plan`, post({ ids })),
  act: (project: number, id: number, action: "approve" | "execute" | "cancel") =>
    request<Investigations>(`${base(project)}/${id}/${action}`, post(action === "cancel" ? undefined : { confirmed: true })),
};
