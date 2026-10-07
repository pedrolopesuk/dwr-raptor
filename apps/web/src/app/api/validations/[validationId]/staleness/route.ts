import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  context: { params: Promise<{ validationId: string }> },
): Promise<Response> {
  const { validationId } = await context.params;
  return toResponse(await handlers.checkValidationStaleness(validationId));
}
