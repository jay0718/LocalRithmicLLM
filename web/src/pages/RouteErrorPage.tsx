import { Link, isRouteErrorResponse, useRouteError } from "react-router";

export function RouteErrorPage() {
  const error = useRouteError();
  const detail = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Unknown error";

  return (
    <div className="card empty" role="alert">
      <h1>Something went wrong</h1>
      <p className="muted">This page failed to load. The rest of the app still works.</p>
      <pre className="mono muted">{detail}</pre>
      <p>
        <a href={window.location.pathname}>Reload this page</a> · <Link to="/gex">Go to GEX</Link>
      </p>
    </div>
  );
}
