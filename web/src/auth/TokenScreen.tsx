import { useState, type FormEvent } from "react";
import { ApiError, consoleApi, unwrap } from "../api/client";
import { Button } from "../components/ui/Button";
import { Field } from "../components/ui/Field";
import { tokenStore } from "./tokenStore";

async function verify(token: string): Promise<string | null> {
  try {
    await unwrap(consoleApi.GET("/connections", { headers: { Authorization: `Bearer ${token}` } }));
    return null;
  } catch (error) {
    if (!(error instanceof ApiError)) return "Unexpected error";
    if (error.status === 401) return "That token is not valid.";
    if (error.status === 503) return "The console has no admin token configured. Set CONSOLE_ADMIN_TOKEN.";
    return error.message;
  }
}

export function TokenScreen({ expired }: { expired: boolean }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const token = value.trim();
    if (!token) return setError("Enter the admin token.");
    setChecking(true);
    setError(null);
    const problem = await verify(token);
    setChecking(false);
    if (problem) setError(problem);
    else tokenStore.set(token);
  }

  return (
    <div className="token-screen">
      <form className="card token-card" onSubmit={submit} noValidate>
        <img src="/favicon.svg" alt="" width={36} height={36} />
        <h1>Sign in</h1>
        <p className="muted">
          {expired
            ? "Your session ended or the token was rejected. Enter it again to continue."
            : "Enter the admin token set as CONSOLE_ADMIN_TOKEN on the server."}
        </p>
        <Field label="Admin token" error={error}>
          {(props) => (
            <input
              {...props}
              className="input"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" busy={checking}>
          {checking ? "Checking…" : "Continue"}
        </Button>
        <p className="muted small">The token is kept for this browser tab only.</p>
      </form>
    </div>
  );
}
