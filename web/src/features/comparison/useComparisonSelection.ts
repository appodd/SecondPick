import { useEffect, useState } from "react";

const maximumSelections = 4;

function storageKey(taskId: number) {
  return `workbench.comparison.${taskId}`;
}

function readSelection(taskId: number) {
  try {
    const value = sessionStorage.getItem(storageKey(taskId));
    if (!value) {
      return [];
    }
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (listingId, index): listingId is number =>
        Number.isSafeInteger(listingId) &&
        listingId > 0 &&
        parsed.indexOf(listingId) === index,
    ).slice(0, maximumSelections);
  } catch {
    return [];
  }
}

export function useComparisonSelection(taskId: number) {
  const [selectedIds, setSelectedIds] = useState<number[]>(() => readSelection(taskId));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedIds(readSelection(taskId));
    setError(null);
  }, [taskId]);

  function save(next: number[]) {
    sessionStorage.setItem(storageKey(taskId), JSON.stringify(next));
    setSelectedIds(next);
  }

  function toggle(listingId: number) {
    if (selectedIds.includes(listingId)) {
      save(selectedIds.filter((selectedId) => selectedId !== listingId));
      setError(null);
      return;
    }
    if (selectedIds.length >= maximumSelections) {
      setError("每个任务最多对比 4 个候选");
      return;
    }
    save([...selectedIds, listingId]);
    setError(null);
  }

  function remove(listingId: number) {
    save(selectedIds.filter((selectedId) => selectedId !== listingId));
    setError(null);
  }

  return { error, remove, selectedIds, toggle };
}
