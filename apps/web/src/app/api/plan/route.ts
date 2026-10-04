import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as {
    model_id?: string;
    question?: string;
    context?: string;
  };
  if (!body.model_id || !body.question) {
    return Response.json(
      {
        ok: false,
        error: {
          code: "bad_request",
          message: "model_id and question are required",
          diagnostics: [],
        },
      },
      { status: 400 },
    );
  }
  return toResponse(await handlers.planExperiment(body.model_id, body.question, body.context));
}
