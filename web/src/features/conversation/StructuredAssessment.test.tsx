import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { AssessmentBatch } from "../../api/types";
import { StructuredAssessment } from "./StructuredAssessment";

afterEach(cleanup);
const batch: AssessmentBatch = {
  id: 1, task_id: 1, operation_id: 1, standard_id: 1, preference_revision_id: 0,
  stale: true, candidate_stale: { "1": true, "2": false }, validity_signature: "new",
  execution_state: "succeeded", input_signature: "input", evidence_signature: "old",
  schema_version: "candidate-assessment-v2", prompt_version: "shopping-research-v5", created_at: "fixture",
  evidence_refs: {}, batch_index: 1,
  result: { criteria: [{ criterion_id: "battery", description: "电池至少90%", priority: "hard", source_message_ids: [1] }],
    assessments: [1, 2].map(listing_id => ({ listing_id, summary: "电池缺少证明", conclusion: "insufficient_evidence",
      judgments: [{ criterion_id: "battery", status: "UNKNOWN", reason: "待核实", source_type: "missing", evidence_refs: [] }] })) },
};

it("shows partial expiry per candidate while retaining unknown judgments and evidence navigation", async () => {
  const select = vi.fn();
  render(<StructuredAssessment batch={batch} onSelectListing={select} />);
  await userEvent.click(screen.getByText("部分候选评估已过期"));
  expect(screen.getByText("其中 1 件候选的要求或证据已变化，请按各商品标记查看。")).toBeVisible();
  expect(screen.getByText("历史判断：要求或该商品证据已变化")).toBeVisible();
  expect(screen.getByText("判断的要求与证据仍适用")).toBeVisible();
  expect(screen.getAllByText(/未知，待核实/)).toHaveLength(2);
  await userEvent.click(screen.getByRole("button", { name: "查看商品 #2 的证据" }));
  expect(select).toHaveBeenCalledWith(2);
});

it("retains the historical fallback for old batches without candidate metadata", async () => {
  render(<StructuredAssessment batch={{ ...batch, candidate_stale: undefined }} onSelectListing={() => {}} />);
  await userEvent.click(screen.getByText("历史逐项评估（要求或证据已变化）"));
  expect(screen.getAllByText("历史判断：要求或该商品证据已变化")).toHaveLength(2);
  expect(screen.queryByText("判断的要求与证据仍适用")).not.toBeInTheDocument();
});
