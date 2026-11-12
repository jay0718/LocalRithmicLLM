import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { Table } from "./Table";
import { Toaster } from "./Toaster";
import { useToast } from "./toast";

test("busy button is disabled and announced", () => {
  render(<Button busy>Save</Button>);
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("aria-busy", "true");
});

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <Dialog
        open={open}
        title="Delete it?"
        onClose={() => setOpen(false)}
        footer={<Button onClick={() => setOpen(false)}>Cancel</Button>}
      >
        <p>Body</p>
      </Dialog>
    </>
  );
}

test("dialog opens with a labelled title and closes", async () => {
  render(<DialogHarness />);
  await userEvent.click(screen.getByRole("button", { name: "Open" }));
  expect(screen.getByRole("dialog", { name: "Delete it?" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByText("Body")).not.toBeInTheDocument();
});

test("dialog closes on Escape (cancel event)", async () => {
  render(<DialogHarness />);
  await userEvent.click(screen.getByRole("button", { name: "Open" }));
  act(() => {
    screen.getByRole("dialog").dispatchEvent(new Event("cancel", { cancelable: true }));
  });
  expect(screen.queryByText("Body")).not.toBeInTheDocument();
});

const columns = [{ key: "name", header: "Name", render: (row: { name: string }) => row.name }];

test("table shows rows, empty and loading states", () => {
  const { rerender } = render(
    <Table caption="Things" columns={columns} rows={[{ name: "A" }]} rowKey={(r) => r.name} />,
  );
  expect(screen.getByRole("cell", { name: "A" })).toBeInTheDocument();
  rerender(<Table caption="Things" columns={columns} rows={[]} rowKey={(r) => r.name} empty="None yet" />);
  expect(screen.getByText("None yet")).toBeInTheDocument();
  rerender(<Table caption="Things" columns={columns} rows={[]} rowKey={(r) => r.name} loading />);
  expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByText("None yet")).not.toBeInTheDocument();
});

function ToastButton() {
  const toast = useToast();
  return <Button onClick={() => toast("error", "It broke")}>Fail</Button>;
}

test("toasts are announced and dismissable", async () => {
  render(
    <Toaster>
      <ToastButton />
    </Toaster>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Fail" }));
  expect(screen.getByRole("status")).toHaveTextContent("It broke");
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.getByRole("status")).not.toHaveTextContent("It broke");
});
