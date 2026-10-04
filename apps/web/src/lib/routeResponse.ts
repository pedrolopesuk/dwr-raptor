import type { HandlerResult } from "./handlers";

/** Adapt a handler result to a Web `Response` (used only by the route files). */
export function toResponse(result: HandlerResult): Response {
  return Response.json(result.body, { status: result.status });
}
