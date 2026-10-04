import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await context.params;
  return toResponse(await handlers.getExperiment(id));
}
