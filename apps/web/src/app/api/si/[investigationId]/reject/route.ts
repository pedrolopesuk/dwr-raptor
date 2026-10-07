import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ investigationId: string }> },
): Promise<Response> {
  const { investigationId } = await context.params;
  const body = (await request.json().catch(() => ({}))) as {
    step_id?: string;
    model_id?: string;
    plan_id?: string;
  };
  if (!body.step_id) {
    return Response.json(
      {
        ok: false,
        error: { code: "bad_request", message: "step_id is required", diagnostics: [] },
      },
      { status: 400 },
    );
  }
  const params: Record<string, unknown> = {};
  if (body.model_id) params.model_id = body.model_id;
  if (body.plan_id) params.plan_id = body.plan_id;
  return toResponse(await handlers.siReject(investigationId, body.step_id, params));
}
