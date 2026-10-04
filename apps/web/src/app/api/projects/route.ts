import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return toResponse(await handlers.listProjects());
}

export async function POST(request: Request): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as { name?: string; model_id?: string };
  if (!body.name) {
    return Response.json(
      { ok: false, error: { code: "bad_request", message: "name is required", diagnostics: [] } },
      { status: 400 },
    );
  }
  return toResponse(await handlers.createProject(body.name, body.model_id));
}
