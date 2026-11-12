import type { components } from "../../api/console";
import { consoleApi, unwrap } from "../../api/client";

export type Connection = components["schemas"]["ConnectionOut"];
export type SystemsResponse = components["schemas"]["SystemsOut"];
export type ConnectionInput = { system_name: string; username: string; password: string };

export const listConnections = () => unwrap(consoleApi.GET("/connections"));
export const listSystems = () => unwrap(consoleApi.GET("/systems"));
export const createConnection = (body: ConnectionInput) => unwrap(consoleApi.POST("/connections", { body }));
export const deleteConnection = (id: number) =>
  unwrap(consoleApi.DELETE("/connections/{connection_id}", { params: { path: { connection_id: id } } }));

/** A blank password keeps the stored one, so it is left out of the request. */
export function updateConnection(id: number, input: ConnectionInput) {
  const body = {
    system_name: input.system_name,
    username: input.username,
    ...(input.password ? { password: input.password } : {}),
  };
  return unwrap(
    consoleApi.PUT("/connections/{connection_id}", { params: { path: { connection_id: id } }, body }),
  );
}
