import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router";
import { routes } from "./app/routes";
import { AuthGate } from "./auth/AuthGate";
import { Toaster } from "./components/ui/Toaster";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/controls.css";
import "./styles/gex.css";
import "./styles/flow.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <Toaster>
      <AuthGate>
        <RouterProvider router={createBrowserRouter(routes)} />
      </AuthGate>
    </Toaster>
  </StrictMode>,
);
