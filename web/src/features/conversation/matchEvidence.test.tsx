import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { judgmentBasis, type Judgment } from "./matchEvidence";
import { ConditionJudgments } from "./ConditionJudgments";

afterEach(cleanup);
const base: Judgment = { criterion_id: "model", status: "MET", source_type: "seller_claim", reason: "卖家声明 Switch 2 Pro，实际型号待核实", evidence_refs: ["detail:1879:saved"] };

it("separates preliminary match from conditional buying advice and seller verification", async () => {
  render(<ConditionJudgments criteria={[{criterion_id:"model",description:"型号符合",priority:"hard",source_refs:["task_goal"],source_message_ids:[]}]}
    assessment={{listing_id:1879,conclusion:"conditional",summary:"有条件保留",judgments:[base]}} />);
  await userEvent.click(screen.getByText("条件匹配与证据 · 卖家自述"));
  expect(screen.getByText(/符合（据当前证据） · 卖家自述 · 实物待核实/)).toBeVisible();
  expect(screen.getByText(/不等于已独立核验或建议立即购买/)).toBeVisible();
});

it.each(["seller_claim", "platform_display", "image_observation", "user_statement", "inference", "missing"] as const)("does not derive verified support from %s or reference counts", source_type => {
  const once=judgmentBasis({...base,source_type});
  expect(judgmentBasis({...base,source_type,evidence_refs:["one","two","six-image-urls"]})).toBe(once);
  expect(once).not.toContain("已核验");
});

it("keeps missing references honest rather than inventing material support", () => {
  expect(judgmentBasis({...base,evidence_refs:[]})).toBe("引用依据缺失 · 核验未确认");
  expect(judgmentBasis({...base,source_type:"image_observation"})).toContain("使用情况待核对");
});

it.each(["UNKNOWN", "CONFLICT", "NOT_MET"] as const)("preserves %s instead of coercing a seller claim to MET", async status => {
  render(<ConditionJudgments assessment={{listing_id:1879,conclusion:"insufficient_evidence",summary:"未知",judgments:[{...base,status}]}} />);
  await userEvent.click(screen.getByText(/条件匹配与证据/));
  expect(screen.queryByText(/符合（据当前证据）/)).not.toBeInTheDocument();
});
