import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ validationId: string }> },
): Promise<Response> {
  const { validationId } = await context.params;
  return toResponse(await handlers.getValidation(validationId));
}
