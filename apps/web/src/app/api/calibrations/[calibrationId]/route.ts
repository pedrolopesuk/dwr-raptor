import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ calibrationId: string }> },
): Promise<Response> {
  const { calibrationId } = await context.params;
  return toResponse(await handlers.getCalibration(calibrationId));
}
