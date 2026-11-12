import { act, renderHook } from "@testing-library/react";
import { json } from "../../test-utils";
import { makeSnapshot } from "./fixtures";
import { useGexStream } from "./useGexStream";

class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  open() {
    this.onopen?.();
  }
  send(snapshot: unknown, bar: unknown = null) {
    this.onmessage?.({ data: JSON.stringify({ underlying: "ESZ6", snapshot, bar }) } as MessageEvent);
  }
  drop() {
    this.onclose?.();
  }
  close() {
    this.closed = true;
  }
}

let now = 1_000_000;
let latest: unknown = null;
let bars: unknown[] = [];
void bars;

beforeEach(() => {
  FakeSocket.all = [];
  now = 1_000_000;
  latest = null;
  bars = [];
  vi.useFakeTimers();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.includes("/bars")) return json(bars);
    return latest ? json(latest) : json({ detail: "none" }, 503);
  });
});

afterEach(() => {
  vi.useRealTimers();
});

function setup() {
  const hook = renderHook(() =>
    useGexStream({
      underlying: "ESZ6",
      createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
      now: () => now,
    }),
  );
  return { hook, socket: () => FakeSocket.all.at(-1) as FakeSocket };
}

const flush = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

test("shows no-data state when the service has no snapshot yet", async () => {
  const { hook } = setup();
  await flush();
  expect(hook.result.current.noData).toBe(true);
  expect(hook.result.current.status).toBe("connecting");
});

test("streams snapshots and ignores older ones within a connection", async () => {
  const { hook, socket } = setup();
  act(() => socket().open());
  act(() => socket().send(makeSnapshot({ as_of_ns: 200, spot: 1 })));
  act(() => socket().send(makeSnapshot({ as_of_ns: 100, spot: 2 })));
  expect(hook.result.current.status).toBe("live");
  expect(hook.result.current.snapshot?.spot).toBe(1);
});

test("keeps the last snapshot and reconnects with backoff after a drop", async () => {
  const { hook, socket } = setup();
  act(() => socket().open());
  act(() => socket().send(makeSnapshot({ as_of_ns: 200 })));
  act(() => socket().drop());
  expect(hook.result.current.status).toBe("reconnecting");
  expect(hook.result.current.snapshot?.as_of_ns).toBe(200);
  expect(FakeSocket.all).toHaveLength(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
  expect(FakeSocket.all).toHaveLength(2);
});

test("after reconnect, reloads the latest snapshot and accepts an earlier market time", async () => {
  // regression: a restarted service starts at an earlier market time and was ignored forever
  const { hook, socket } = setup();
  act(() => socket().open());
  act(() => socket().send(makeSnapshot({ as_of_ns: 900 })));
  act(() => socket().drop());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
  latest = { underlying: "ESZ6", snapshot: makeSnapshot({ as_of_ns: 100, spot: 42 }), bar: null };
  act(() => socket().open());
  await flush();
  expect(hook.result.current.status).toBe("live");
  expect(hook.result.current.snapshot?.spot).toBe(42);
});

test("marks the feed stale after 5 seconds without messages", async () => {
  const { hook, socket } = setup();
  act(() => socket().open());
  act(() => socket().send(makeSnapshot()));
  now += 6000;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(hook.result.current.status).toBe("stale");
  act(() => socket().send(makeSnapshot({ as_of_ns: makeSnapshot().as_of_ns + 1 })));
  expect(hook.result.current.status).toBe("live");
});

test("ignores malformed frames and closes the socket on unmount", async () => {
  const { hook, socket } = setup();
  act(() => socket().open());
  act(() => socket().onmessage?.({ data: "{not json" } as MessageEvent));
  expect(hook.result.current.snapshot).toBeNull();
  hook.unmount();
  expect(socket().closed).toBe(true);
});

const bar = (start_ns: number, close: number) => ({
  start_ns,
  open: close,
  high: close,
  low: close,
  close,
  volume: 1,
  trades: 1,
});

test("exposes the live minute bar and counts connections", async () => {
  const { hook, socket } = setup();
  act(() => socket().open());
  expect(hook.result.current.connection).toBe(1);
  act(() => socket().send(makeSnapshot(), bar(120, 3)));
  expect(hook.result.current.liveBar?.close).toBe(3);
  act(() => socket().send(null, bar(120, 4)));
  expect(hook.result.current.liveBar?.close).toBe(4);
  expect(hook.result.current.snapshot).not.toBeNull();
});

test("switching underlying clears the previous symbol's data", async () => {
  const hook = renderHook(
    ({ underlying }) =>
      useGexStream({
        underlying,
        createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
        now: () => now,
      }),
    { initialProps: { underlying: "ESZ6" } },
  );
  act(() => FakeSocket.all.at(-1)?.open());
  act(() => FakeSocket.all.at(-1)?.send(makeSnapshot()));
  expect(hook.result.current.snapshot).not.toBeNull();
  hook.rerender({ underlying: "NQZ6" });
  expect(hook.result.current.snapshot).toBeNull();
  expect(FakeSocket.all.at(-1)?.url).toContain("underlying=NQZ6");
});

test("expiry count is part of the stream address and resets state", async () => {
  const hook = renderHook(
    ({ expiries }: { expiries: number | null }) =>
      useGexStream({
        underlying: "ESZ6",
        expiries,
        createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
        now: () => now,
      }),
    { initialProps: { expiries: null as number | null } },
  );
  act(() => FakeSocket.all.at(-1)?.open());
  act(() => FakeSocket.all.at(-1)?.send(makeSnapshot()));
  expect(FakeSocket.all.at(-1)?.url).not.toContain("expiries=");
  hook.rerender({ expiries: 1 });
  expect(hook.result.current.snapshot).toBeNull();
  expect(FakeSocket.all.at(-1)?.url).toContain("underlying=ESZ6&expiries=1");
});
