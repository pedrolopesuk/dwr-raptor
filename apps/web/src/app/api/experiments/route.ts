import { handlers } from "@/lib/handlers";
import { toResponse } from "@/lib/routeResponse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const projectId = new URL(request.url).searchParams.get("project_id") ?? undefined;
  return toResponse(await handlers.listExperiments(projectId));
}

export async function POST(request: Request): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as {
    spec?: unknown;
    project_id?: string;
    job_id?: string;
  };
  return toResponse(
    await handlers.run(body.spec, {
      signal: request.signal,
      projectId: body.project_id,
      jobId: body.job_id,
    }),
  );
}
