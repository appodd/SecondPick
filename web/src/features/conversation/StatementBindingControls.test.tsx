import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { StatementBindingControls } from "./StatementBindingControls";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function setup(status: "active" | "withdrawn" = "active") {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  client.setQueryData(["task", 1], { existing: true });
  const select = vi.fn();
  render(<QueryClientProvider client={client}><StatementBindingControls taskId={1}
    binding={{ id: 7, listing_id: 2, kind: "seller_reply", status, revision_id: 4, original_listing_id: 1 }} onSelectListing={select} /></QueryClientProvider>);
  return { client, select };
}

it("corrects explicit target and purpose with the displayed revision", async () => {
  const change = vi.spyOn(api, "changeStatement").mockResolvedValue({ id: 7, listing_id: 3, kind: "user_observation", revision_id: 5 });
  const { client } = setup();
  await userEvent.click(screen.getByRole("button", { name: "更正归属" }));
  await userEvent.clear(screen.getByRole("spinbutton"));
  await userEvent.type(screen.getByRole("spinbutton"), "3");
  await userEvent.selectOptions(screen.getByRole("combobox"), "user_observation");
  await userEvent.click(screen.getByRole("button", { name: "保存更正" }));
  await waitFor(() => expect(change).toHaveBeenCalledWith(1, 7, { action: "rebind", listing_id: 3, kind: "user_observation", expected_revision_id: 4 }));
  expect(client.getQueryState(["task", 1])?.isInvalidated).toBe(true);
  expect(screen.getByRole("status")).toHaveTextContent("重新分析");
});

it("withdraws without deleting text or implicitly launching analysis", async () => {
  const change = vi.spyOn(api, "changeStatement").mockResolvedValue({ id: 7, listing_id: 2, kind: "seller_reply", status: "withdrawn" });
  const send = vi.spyOn(api, "sendMessage");
  setup();
  await userEvent.click(screen.getByRole("button", { name: "撤回此补充" }));
  expect(change).toHaveBeenCalledWith(1, 7, { action: "withdraw", expected_revision_id: 4 });
  expect(send).not.toHaveBeenCalled();
});

it("retains failed draft and shows scope/conflict errors", async () => {
  vi.spyOn(api, "changeStatement").mockRejectedValue(new Error("补充已被其他操作修改"));
  setup();
  await userEvent.click(screen.getByRole("button", { name: "更正归属" }));
  await userEvent.clear(screen.getByRole("spinbutton"));
  await userEvent.type(screen.getByRole("spinbutton"), "999");
  await userEvent.click(screen.getByRole("button", { name: "保存更正" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("其他操作修改");
  expect(screen.getByRole("spinbutton")).toHaveValue(999);
});

it("displays withdrawal and original attribution after reload without restore controls", async () => {
  const { select } = setup("withdrawn");
  expect(screen.getByText(/原文保留/)).toBeVisible();
  expect(screen.getByText(/原绑定 #1/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "更正归属" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "查看绑定商品证据" }));
  expect(select).toHaveBeenCalledWith(2);
});
