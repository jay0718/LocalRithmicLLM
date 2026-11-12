import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { RouteErrorPage } from "../pages/RouteErrorPage";
import { AppShell } from "./AppShell";
import { routes } from "./routes";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

test("redirects the root to GEX", async () => {
  const router = renderAt("/");
  expect(await screen.findByRole("heading", { name: "GEX" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/gex");
});

test.each([
  ["/connections", "Connections"],
  ["/gateway", "LLM gateway"],
])("%s renders its page and marks the nav item", async (path, title) => {
  renderAt(path);
  expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: title })).toHaveAttribute("aria-current", "page");
});

test("navigates with the sidebar", async () => {
  const router = renderAt("/gex");
  await userEvent.click(await screen.findByRole("link", { name: "Connections" }));
  expect(router.state.location.pathname).toBe("/connections");
});

test("unknown paths show not found inside the shell", async () => {
  renderAt("/nope");
  expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
});

test("a render error shows the error page and keeps navigation", async () => {
  const Boom = () => {
    throw new Error("kaboom");
  };
  const router = createMemoryRouter(
    [
      {
        element: <AppShell />,
        children: [{ errorElement: <RouteErrorPage />, children: [{ path: "x", element: <Boom /> }] }],
      },
    ],
    { initialEntries: ["/x"] },
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(<RouterProvider router={router} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("kaboom");
  expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
});
