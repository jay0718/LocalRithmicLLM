/** Replace fetch with a handler keyed by "METHOD /path" that returns JSON responses. */
export type Handler = (request: Request) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function mockFetch(routes: Record<string, Handler>) {
  const calls: Request[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    // Resolve relative URLs as a browser would.
    const request =
      input instanceof Request ? input : new Request(new URL(String(input), window.location.href), init);
    calls.push(request);
    const url = new URL(request.url);
    const handler = routes[`${request.method} ${url.pathname}`];
    if (!handler) return json({ detail: `No mock for ${request.method} ${url.pathname}` }, 404);
    return handler(request);
  });
  return calls;
}
