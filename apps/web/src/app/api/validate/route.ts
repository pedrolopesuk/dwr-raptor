import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as { spec?: unknown };
  return toResponse(await handlers.validate(body.spec, request.signal));
}
