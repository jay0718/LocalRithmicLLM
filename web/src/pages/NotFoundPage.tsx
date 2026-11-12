import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <div className="card empty">
      <h1>Page not found</h1>
      <p className="muted">There is nothing at this address.</p>
      <Link to="/gex">Go to GEX</Link>
    </div>
  );
}
