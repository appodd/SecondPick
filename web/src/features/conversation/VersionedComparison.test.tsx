import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { HistoryReview } from "../../api/types";
import { ReviewProgress } from "./VersionedComparison";

afterEach(cleanup);
const review: HistoryReview = {
  id: 2, task_id: 1, operation_id: 2, standard_id: 1, preference_revision_id: 0,
  state: "failed", error_detail: "timeout", stale: false, created_at: "fixture",
  coverage: { scope_count: 23, reviewed_count: 23, assessed_count: 23, pending_count: 0, truncated: false },
  nomination_progress: { required: true, total_groups: 2, completed_groups: 1, pending_groups: 1 },
};

it("does not call a review complete when assessments finished but nomination failed", () => {
  render(<ReviewProgress review={review} batches={[]} onSelectListing={() => {}} />);
  expect(screen.getByText("候选重评未完成")).toBeVisible();
  expect(screen.getByText(/重新提名进度：已保存 1\/2 组；完成后生成完整比较/)).toBeVisible();
  expect(screen.getByText(/本次未发布新比较/)).toBeVisible();
});

it("restores completed nomination progress separately from candidate counts", () => {
  render(<ReviewProgress review={{ ...review, state: "completed", nomination_progress: {
    required: true, total_groups: 2, completed_groups: 2, pending_groups: 0 } }} batches={[]} onSelectListing={() => {}} />);
  expect(screen.getByText("候选重评已完成")).toBeVisible();
  expect(screen.getByText(/重新提名进度：已保存 2\/2 组；提名已完成/)).toBeVisible();
});
