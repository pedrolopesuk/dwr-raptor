import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ investigationId: string }> },
): Promise<Response> {
  const { investigationId } = await context.params;
  const url = new URL(request.url);
  const params: Record<string, unknown> = {};
  const modelId = url.searchParams.get("model_id");
  const projectId = url.searchParams.get("project_id");
  if (modelId) params.model_id = modelId;
  if (projectId) params.project_id = projectId;
  return toResponse(await handlers.siState(investigationId, params));
}
