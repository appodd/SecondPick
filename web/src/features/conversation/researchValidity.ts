/** Cached older pages must follow the newest known task inputs during refetch. */
export function applyCurrentInputs<T extends { preference_revision_id: number; stale: boolean; evidence_signature?: string;
  validity_signature?: string; candidate_stale?: Record<string, boolean> }>(
  records: T[], revision: number, evidenceSignature?: string,
): T[] {
  return records.map(record => {
    const checkedSignature = record.validity_signature ?? record.evidence_signature;
    const changed = record.preference_revision_id !== revision ||
      Boolean(evidenceSignature && checkedSignature && evidenceSignature !== checkedSignature);
    return { ...record, stale: record.stale || changed,
      ...(record.candidate_stale && changed ? { candidate_stale:
        Object.fromEntries(Object.keys(record.candidate_stale).map(id => [id, true])) } : {}) };
  });
}
