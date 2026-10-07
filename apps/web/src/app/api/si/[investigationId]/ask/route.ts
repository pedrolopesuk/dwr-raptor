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
    question?: string;
    model_id?: string;
    project_id?: string;
  };
  if (!body.question) {
    return Response.json(
      {
        ok: false,
        error: { code: "bad_request", message: "question is required", diagnostics: [] },
      },
      { status: 400 },
    );
  }
  const params: Record<string, unknown> = {};
  if (body.model_id) params.model_id = body.model_id;
  if (body.project_id) params.project_id = body.project_id;
  return toResponse(await handlers.siAsk(investigationId, body.question, params));
}
