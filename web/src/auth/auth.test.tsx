import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test-utils";
import { AuthGate } from "./AuthGate";
import { tokenStore } from "./tokenStore";

beforeEach(() => tokenStore.clear());

function renderGate() {
  render(
    <AuthGate>
      <p>Signed in content</p>
    </AuthGate>,
  );
}

test("valid token signs in and is stored for the tab", async () => {
  mockFetch({
    "GET /api/console/connections": (request) =>
      request.headers.get("Authorization") === "Bearer good" ? json([]) : json({ detail: "x" }, 401),
  });
  renderGate();
  await userEvent.type(screen.getByLabelText("Admin token"), "good");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByText("Signed in content")).toBeInTheDocument();
  expect(sessionStorage.getItem("lrl.adminToken")).toBe("good");
});

test.each([
  [401, "That token is not valid."],
  [503, "The console has no admin token configured. Set CONSOLE_ADMIN_TOKEN."],
])("rejected token (%s) shows a clear error", async (status, message) => {
  mockFetch({ "GET /api/console/connections": () => json({ detail: "x" }, status) });
  renderGate();
  await userEvent.type(screen.getByLabelText("Admin token"), "bad");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.getByLabelText("Admin token")).toHaveAttribute("aria-invalid", "true");
});

test("empty token is not sent", async () => {
  const calls = mockFetch({});
  renderGate();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter the admin token.");
  expect(calls).toHaveLength(0);
});

test("expiry returns to the token screen with an explanation", async () => {
  tokenStore.set("good");
  renderGate();
  expect(screen.getByText("Signed in content")).toBeInTheDocument();
  tokenStore.expire();
  expect(await screen.findByText(/session ended or the token was rejected/)).toBeInTheDocument();
});

test("sign out clears the token", async () => {
  tokenStore.set("good");
  renderGate();
  tokenStore.clear();
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(sessionStorage.getItem("lrl.adminToken")).toBeNull();
});
