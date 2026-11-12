/** The admin token lives in sessionStorage, so it is cleared when the tab closes. */
const KEY = "lrl.adminToken";
type Listener = (token: string | null, reason: "signin" | "signout" | "expired") => void;
const listeners = new Set<Listener>();

function read(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function write(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    // Storage can be unavailable in private windows; the token then lasts for this page only.
  }
}

let current = read();

export const tokenStore = {
  get: () => current,
  set(token: string) {
    current = token;
    write(token);
    listeners.forEach((listener) => listener(token, "signin"));
  },
  clear() {
    current = null;
    write(null);
    listeners.forEach((listener) => listener(null, "signout"));
  },
  expire() {
    if (current === null) return;
    current = null;
    write(null);
    listeners.forEach((listener) => listener(null, "expired"));
  },
  subscribe(listener: Listener) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
