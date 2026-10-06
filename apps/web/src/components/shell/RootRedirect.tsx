"use client";

import { useEffect, useMemo, useState } from "react";

import { useRouter } from "next/navigation";

import { InlineLoading } from "@carbon/react";

import { createFetchClient } from "@/lib/client";
import { paths } from "@/lib/routes";

/** `/` has no content of its own: it opens the first project. */
export function RootRedirect() {
  const router = useRouter();
  const api = useMemo(() => createFetchClient(), []);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const projects = await api.listProjects();
        const first = projects[0];
        if (first) router.replace(paths.project(first.project_id));
        else setProblem("This workspace has no projects.");
      } catch (error) {
        setProblem(error instanceof Error ? error.message : "Projects could not be loaded.");
      }
    })();
  }, [api, router]);

  return (
    <div className="drw-boot" data-testid="root-redirect">
      {problem ? <p role="alert">{problem}</p> : <InlineLoading description="Opening your project" />}
    </div>
  );
}
