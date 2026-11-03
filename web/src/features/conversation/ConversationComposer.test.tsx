import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ConversationComposer } from "./ConversationComposer";

afterEach(cleanup);

it("requires an explicit purpose and candidate before sending a relayed reply", async () => {
  const send = vi.fn().mockResolvedValue(undefined);
  render(<ConversationComposer allowStatements onSend={send} />);
  await userEvent.type(screen.getByRole("textbox", { name: "对话输入" }), "他说没修过");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "消息用途" }), "seller_reply");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(send).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("请指定当前任务的商品编号");
  await userEvent.type(screen.getByRole("spinbutton", { name: "证据所属商品编号" }), "205");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(send).toHaveBeenCalledWith("他说没修过", { listing_id: 205, kind: "seller_reply" });
  expect(screen.getByRole("combobox", { name: "消息用途" })).toHaveValue("chat");
});

it("does not implicitly turn ordinary messages about a selected candidate into evidence", async () => {
  const send = vi.fn().mockResolvedValue(undefined);
  render(<ConversationComposer allowStatements selectedListingId={2} onSend={send} />);
  await userEvent.type(screen.getByRole("textbox", { name: "对话输入" }), "B靠谱吗");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(send).toHaveBeenCalledWith("B靠谱吗", undefined);
});

it("prefills the inspected candidate only after choosing an evidence purpose and preserves failed drafts", async () => {
  const send = vi.fn().mockRejectedValue(new Error("商品不属于当前任务"));
  render(<ConversationComposer allowStatements selectedListingId={2} onSend={send} />);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "消息用途" }), "user_observation");
  expect(screen.getByRole("spinbutton", { name: "证据所属商品编号" })).toHaveValue(2);
  await userEvent.type(screen.getByRole("textbox", { name: "对话输入" }), "我看到边框磕碰");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(screen.getByRole("alert")).toHaveTextContent("商品不属于当前任务");
  expect(screen.getByRole("textbox", { name: "对话输入" })).toHaveValue("我看到边框磕碰");
  expect(screen.getByRole("combobox", { name: "消息用途" })).toHaveValue("user_observation");
});

it("does not offer binding before a task exists", () => {
  render(<ConversationComposer onSend={vi.fn()} />);
  expect(screen.queryByRole("combobox", { name: "消息用途" })).not.toBeInTheDocument();
});
