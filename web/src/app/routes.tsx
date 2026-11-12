import type { RouteObject } from "react-router";
import { Navigate } from "react-router";
import { ConnectionsPage } from "../features/connections/ConnectionsPage";
import { GatewayPage } from "../pages/GatewayPage";
import { FlowPage } from "../features/flow/FlowPage";
import { GexPage } from "../features/gex/GexPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { RouteErrorPage } from "../pages/RouteErrorPage";
import { AppShell } from "./AppShell";

export const NAV_ITEMS = [
  { to: "/gex", label: "GEX" },
  { to: "/flow", label: "Flow nodes" },
  { to: "/connections", label: "Connections" },
  { to: "/gateway", label: "LLM gateway" },
] as const;

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    errorElement: <RouteErrorPage />,
    children: [
      {
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <Navigate to="/gex" replace /> },
          { path: "gex", element: <GexPage /> },
          { path: "flow", element: <FlowPage /> },
          { path: "connections", element: <ConnectionsPage /> },
          { path: "gateway", element: <GatewayPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
