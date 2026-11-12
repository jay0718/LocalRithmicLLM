import { useEffect, useState, type ReactNode } from "react";
import { TokenScreen } from "./TokenScreen";
import { tokenStore } from "./tokenStore";

/** Shows the token screen until the user has a valid admin token, and again whenever it is rejected. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(tokenStore.get);
  const [expired, setExpired] = useState(false);

  useEffect(
    () =>
      tokenStore.subscribe((next, reason) => {
        setToken(next);
        setExpired(reason === "expired");
      }),
    [],
  );

  if (!token) return <TokenScreen expired={expired} />;
  return <>{children}</>;
}
