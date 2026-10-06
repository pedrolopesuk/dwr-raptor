"use client";

import { useEffect } from "react";

import { useRouter } from "next/navigation";

import { paths, useRoute } from "@/lib/routes";

/** /investigations/:id opens the investigation's SI page. */
export function InvestigationIndexRedirect() {
  const router = useRouter();
  const route = useRoute();
  useEffect(() => {
    if (route.projectId && route.investigationId) {
      router.replace(paths.investigation(route.projectId, route.investigationId, "si"));
    }
  }, [route.projectId, route.investigationId, router]);
  return null;
}
