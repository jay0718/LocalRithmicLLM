import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { tokenStore } from "../../auth/tokenStore";
import { Toaster } from "../../components/ui/Toaster";
import { json, mockFetch, type Handler } from "../../test-utils";
import type { Connection } from "./api";
import { ConnectionsPage } from "./ConnectionsPage";

const SYSTEMS = {
  systems: [
    { name: "Apex", is_test: false },
    { name: "Bulenox", is_test: false },
    { name: "Rithmic Test", is_test: true },
  ],
  cached: false,
  fetched_at: Date.now() / 1000,
};

const APEX: Connection = {
  id: 1,
  system_name: "Apex",
  username: "trader1",
  status: "untested",
  last_checked_at: null,
  created_at: 0,
};

beforeEach(() => tokenStore.set("t"));

function setup(routes: Record<string, Handler> = {}) {
  let connections: Connection[] = [];
  const calls = mockFetch({
    "GET /api/console/connections": () => json(connections),
    "GET /api/console/systems": () => json(SYSTEMS),
    ...routes,
  });
  const setConnections = (next: Connection[]) => {
    connections = next;
  };
  render(
    <Toaster>
      <ConnectionsPage />
    </Toaster>,
  );
  return { calls, setConnections };
}

async function chooseFirm(name: string) {
  const firm = screen.getByRole("combobox", { name: "Firm" });
  await userEvent.type(firm, name.slice(0, 3));
  await userEvent.click(screen.getByRole("option", { name }));
}

test("empty state offers to add a connection", async () => {
  setup();
  expect(await screen.findByRole("heading", { name: "No connections yet" })).toBeInTheDocument();
});

test("lists connections with status and actions", async () => {
  mockFetch({
    "GET /api/console/connections": () => json([APEX]),
    "GET /api/console/systems": () => json(SYSTEMS),
  });
  render(<ConnectionsPage />);
  const row = (await screen.findByText("trader1")).closest("tr");
  expect(row).not.toBeNull();
  expect(within(row as HTMLElement).getByText("Not tested")).toBeInTheDocument();
  expect(within(row as HTMLElement).getByText("Never")).toBeInTheDocument();
});

test("load error shows a retry", async () => {
  let fail = true;
  mockFetch({
    "GET /api/console/connections": () => (fail ? json({ detail: "boom" }, 500) : json([APEX])),
    "GET /api/console/systems": () => json(SYSTEMS),
  });
  render(<ConnectionsPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load connections: boom");
  fail = false;
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("trader1")).toBeInTheDocument();
});

test("adds a connection", async () => {
  let sent: unknown;
  const { setConnections } = setup({
    "POST /api/console/connections": async (request) => {
      const body = await request.json();
      sent = body;
      setConnections([{ ...APEX, ...body }]);
      return json({ ...APEX, ...body }, 201);
    },
  });
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  await chooseFirm("Apex");
  await userEvent.type(screen.getByLabelText("Username"), "trader1");
  await userEvent.type(screen.getByLabelText("Password"), "pw");
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add connection" }));
  expect(await screen.findByText("Connection added")).toBeInTheDocument();
  expect(sent).toEqual({ system_name: "Apex", username: "trader1", password: "pw" });
  expect(await screen.findByText("trader1")).toBeInTheDocument();
});

test("validates required fields before sending", async () => {
  const { calls } = setup();
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add connection" }));
  expect(screen.getByText("Choose a firm from the list.")).toBeInTheDocument();
  expect(screen.getByText("Enter the Rithmic username.")).toBeInTheDocument();
  expect(screen.getByText("Enter the Rithmic password.")).toBeInTheDocument();
  expect(calls.some((call) => call.method === "POST")).toBe(false);
});

test("typed text that isn't a listed firm is not accepted", async () => {
  setup();
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  await userEvent.type(screen.getByRole("combobox", { name: "Firm" }), "Made Up Firm");
  expect(screen.getByText(/No firms match/)).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add connection" }));
  expect(screen.getByText("Choose a firm from the list.")).toBeInTheDocument();
});

test("duplicate connection error appears on the username field", async () => {
  setup({ "POST /api/console/connections": () => json({ detail: "That connection already exists" }, 409) });
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  await chooseFirm("Apex");
  await userEvent.type(screen.getByLabelText("Username"), "trader1");
  await userEvent.type(screen.getByLabelText("Password"), "pw");
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add connection" }));
  expect(
    await screen.findByText("A connection for this firm and username already exists."),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Username")).toHaveAttribute("aria-invalid", "true");
});

test("server field errors map to their fields", async () => {
  setup({
    "POST /api/console/connections": () =>
      json(
        { detail: [{ loc: ["body", "username"], msg: "String should have at most 200 characters" }] },
        422,
      ),
  });
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  await chooseFirm("Apex");
  await userEvent.type(screen.getByLabelText("Username"), "x");
  await userEvent.type(screen.getByLabelText("Password"), "pw");
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add connection" }));
  expect(await screen.findByText("String should have at most 200 characters")).toBeInTheDocument();
});

test("test systems are hidden until requested", async () => {
  setup();
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  await userEvent.click(screen.getByRole("combobox", { name: "Firm" }));
  expect(screen.queryByRole("option", { name: /Rithmic Test/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Show test systems"));
  await userEvent.click(screen.getByRole("combobox", { name: "Firm" }));
  expect(screen.getByRole("option", { name: /Rithmic Test/ })).toBeInTheDocument();
});

test("firm selector works by keyboard", async () => {
  setup();
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  const firm = screen.getByRole("combobox", { name: "Firm" });
  await userEvent.type(firm, "b");
  await userEvent.keyboard("{Enter}");
  expect(firm).toHaveValue("Bulenox");
});

test("cached firm list shows a banner", async () => {
  setup({
    "GET /api/console/systems": () =>
      json({ ...SYSTEMS, cached: true, fetched_at: Date.now() / 1000 - 7200 }),
  });
  await userEvent.click(await screen.findByRole("button", { name: "Add connection" }));
  expect(await screen.findByText(/couldn't be refreshed.*2 hours ago/)).toBeInTheDocument();
});

test("edit with a blank password leaves it out of the request", async () => {
  let sent: unknown;
  mockFetch({
    "GET /api/console/connections": () => json([APEX]),
    "GET /api/console/systems": () => json(SYSTEMS),
    "PUT /api/console/connections/1": async (request) => {
      sent = await request.json();
      return json({ ...APEX, username: "renamed" });
    },
  });
  render(
    <Toaster>
      <ConnectionsPage />
    </Toaster>,
  );
  await userEvent.click(await screen.findByRole("button", { name: "Edit Apex trader1" }));
  expect(screen.getByLabelText("Password")).toHaveValue("");
  expect(screen.getByText("Leave blank to keep the saved password.")).toBeInTheDocument();
  await userEvent.clear(screen.getByLabelText("Username"));
  await userEvent.type(screen.getByLabelText("Username"), "renamed");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(sent).toEqual({ system_name: "Apex", username: "renamed" }));
});

test("delete asks for confirmation naming the connection", async () => {
  let deleted = false;
  mockFetch({
    "GET /api/console/connections": () => json(deleted ? [] : [APEX]),
    "GET /api/console/systems": () => json(SYSTEMS),
    "DELETE /api/console/connections/1": () => {
      deleted = true;
      return new Response(null, { status: 204 });
    },
  });
  render(
    <Toaster>
      <ConnectionsPage />
    </Toaster>,
  );
  await userEvent.click(await screen.findByRole("button", { name: "Delete Apex trader1" }));
  const dialog = screen.getByRole("dialog", { name: "Delete connection?" });
  expect(dialog).toHaveTextContent("Apex · trader1");
  expect(deleted).toBe(false);
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(await screen.findByRole("heading", { name: "No connections yet" })).toBeInTheDocument();
});
