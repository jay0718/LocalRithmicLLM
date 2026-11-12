import { tokenStore } from "../auth/tokenStore";
import { json, mockFetch } from "../test-utils";
import { ApiError, consoleApi, parseErrorBody, unwrap } from "./client";

test.each([
  [{ detail: "Connection not found" }, "Connection not found", {}],
  [{ error: { message: "Unknown model" } }, "Unknown model", {}],
  [
    { detail: [{ loc: ["body", "username"], msg: "Field required" }] },
    "Some fields need attention",
    { username: "Field required" },
  ],
  [null, "Request failed (500)", {}],
])("parses error body %j", (body, message, fields) => {
  const error = parseErrorBody(500, body);
  expect(error.message).toBe(message);
  expect(error.fieldErrors).toEqual(fields);
});

test("adds the bearer token", async () => {
  tokenStore.set("secret");
  const calls = mockFetch({ "GET /api/console/connections": () => json([]) });
  await unwrap(consoleApi.GET("/connections"));
  expect(calls[0]?.headers.get("Authorization")).toBe("Bearer secret");
});

test("a 401 expires the token and raises ApiError", async () => {
  tokenStore.set("old");
  const reasons: string[] = [];
  const unsubscribe = tokenStore.subscribe((_, reason) => reasons.push(reason));
  mockFetch({ "GET /api/console/connections": () => json({ detail: "Invalid admin token" }, 401) });
  await expect(unwrap(consoleApi.GET("/connections"))).rejects.toMatchObject({ status: 401 });
  expect(tokenStore.get()).toBeNull();
  expect(reasons).toEqual(["expired"]);
  unsubscribe();
});

test("network failures become ApiError with status 0", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  const error = await unwrap(consoleApi.GET("/connections")).catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 0, message: "Could not reach the server" });
});
