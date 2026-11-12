import { act, renderHook, waitFor } from "@testing-library/react";
import { json, mockFetch } from "../../test-utils";
import { mergeFrame, useFlowLive, type NodeFrame } from "./useFlowHistory";

const MINUTE = 60_000_000_000;
const T0 = 1_794_324_660_000_000_000; // 2026-11-10 9:31 AM ET
const PRIOR_CLOSE = 1_794_262_440_000_000_000; // 2026-11-09 4:14 PM ET

const frame = (ts_ns: number, value: number): NodeFrame => ({
  ts_ns,
  spot: 675,
  nodes: [{ strike: 674, value }],
  call_wall: null,
  put_wall: 674,
  flip: null,
  total: value,
  computed_ns: 0,
});

test("a frame in the same market minute replaces the last one; a new minute appends", () => {
  const one = mergeFrame([], frame(T0, -1));
  const replaced = mergeFrame(one, frame(T0 + 20_000_000_000, -2));
  expect(replaced).toHaveLength(1);
  expect(replaced[0]?.total).toBe(-2);
  expect(mergeFrame(replaced, frame(T0 + MINUTE, -3))).toHaveLength(2);
  expect(mergeFrame(replaced, frame(T0 - MINUTE, 9))).toBe(replaced);
});

test("loads the session so far, then takes overnight and minute frames from the stream", async () => {
  mockFetch({
    "GET /api/gex/flow/live": () =>
      json({
        symbol: "QQQ",
        expiry: "20261110",
        session_date: "2026-11-10",
        ratio: 41.25,
        frames: [frame(T0, -1)],
      }),
    "GET /api/gex/bars": () => json([]),
  });
  const sockets: { url: string; onmessage: ((event: MessageEvent) => void) | null }[] = [];
  const createSocket = (url: string) => {
    const socket = { url, onmessage: null, onclose: null, close: () => undefined };
    sockets.push(socket);
    return socket as unknown as WebSocket;
  };
  const { result } = renderHook(() => useFlowLive("NQZ6", true, createSocket));
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect(sockets[0]?.url).toContain("/api/gex/ws/flow?underlying=NQZ6");
  const send = (f: NodeFrame) =>
    act(() => sockets[0]?.onmessage?.({ data: JSON.stringify(f) } as MessageEvent));
  send(frame(T0 + MINUTE, -5));
  send(frame(PRIOR_CLOSE, 7));
  // Frames are applied together on the next paint.
  await waitFor(() => expect(result.current.data?.history.overnight?.total).toBe(7));
  expect(result.current.data?.history.frames.map((f) => f.total)).toEqual([-1, -5]);
});

test("streaming mode loads 10-second frames and keeps each 10 seconds as its own frame", async () => {
  const calls = mockFetch({
    "GET /api/gex/flow/live": () =>
      json({
        symbol: "QQQ",
        expiry: "20261110",
        session_date: "2026-11-10",
        ratio: 41.25,
        frames: [frame(T0, -1)],
      }),
    "GET /api/gex/bars": () => json([]),
  });
  const urls: string[] = [];
  const createSocket = (url: string) => {
    urls.push(url);
    return { url, onmessage: null, onclose: null, close: () => undefined } as unknown as WebSocket;
  };
  const sockets: { onmessage: ((event: MessageEvent) => void) | null }[] = [];
  const streamSocket = (url: string) => {
    const socket = createSocket(url) as unknown as { onmessage: ((event: MessageEvent) => void) | null };
    sockets.push(socket);
    return socket as unknown as WebSocket;
  };
  const { result } = renderHook(() => useFlowLive("NQZ6", true, streamSocket, undefined, true));
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect(calls.find((call) => call.url.includes("/flow/live"))?.url).toContain("stream=true");
  // Frames 20 s apart in the same minute stay separate.
  act(() =>
    sockets[0]?.onmessage?.({ data: JSON.stringify(frame(T0 + 20_000_000_000, -2)) } as MessageEvent),
  );
  await waitFor(() => expect(result.current.data?.history.frames.map((f) => f.total)).toEqual([-1, -2]));
  expect(urls).toHaveLength(1);
});
