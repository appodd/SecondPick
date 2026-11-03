import { describe, expect, it } from "vitest";
import { applyCurrentInputs } from "./researchValidity";

describe("previously loaded research while newer task data arrives", () => {
  const cached = { id: 10, preference_revision_id: 7, evidence_signature: "old-evidence", stale: false };
  it("marks older cached pages as historical as soon as requirements change", () => {
    expect(applyCurrentInputs([cached], 8, "old-evidence")[0].stale).toBe(true);
    expect(cached.stale).toBe(false);
  });
  it("marks cached comparisons historical when saved evidence changes without a new preference", () => {
    expect(applyCurrentInputs([cached], 7, "new-evidence")[0].stale).toBe(true);
  });
  it("keeps the current compatible assessment available", () => {
    expect(applyCurrentInputs([cached], 7, "old-evidence")[0].stale).toBe(false);
  });
  it("does not clear an already historical server result when inputs match", () => {
    expect(applyCurrentInputs([{ ...cached, stale: true }], 7, "old-evidence")[0].stale).toBe(true);
  });
  it("keeps a server-revalidated candidate batch current after unrelated evidence changes", () => {
    const batch = { ...cached, validity_signature: "new-evidence", candidate_stale: { "1": false, "2": false } };
    expect(applyCurrentInputs([batch], 7, "new-evidence")[0]).toEqual(batch);
  });
  it("preserves partial invalidation from the server", () => {
    const batch = { ...cached, stale: true, validity_signature: "new-evidence", candidate_stale: { "1": true, "2": false } };
    expect(applyCurrentInputs([batch], 7, "new-evidence")[0]).toEqual(batch);
  });
  it("temporarily invalidates every cached candidate until new evidence is revalidated", () => {
    const batch = { ...cached, validity_signature: "old-evidence", candidate_stale: { "1": false, "2": false } };
    const current = applyCurrentInputs([batch], 7, "new-evidence")[0];
    expect(current.stale).toBe(true);
    expect(current.candidate_stale).toEqual({ "1": true, "2": true });
    expect(batch.candidate_stale).toEqual({ "1": false, "2": false });
  });
  it("invalidates all candidates on requirement changes even if evidence was revalidated", () => {
    const batch = { ...cached, validity_signature: "new-evidence", candidate_stale: { "1": false } };
    expect(applyCurrentInputs([batch], 8, "new-evidence")[0].candidate_stale).toEqual({ "1": true });
  });
});
