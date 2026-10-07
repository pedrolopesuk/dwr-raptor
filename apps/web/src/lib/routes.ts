"use client";

import { usePathname } from "next/navigation";

/**
 * Route model.
 *
 * DRW has no backend "investigation" entity. An investigation is a stored
 * experiment (its hypothesis is the question), so `investigationId` is an
 * experiment id. `draft` is the not-yet-run configuration held in the session.
 */
export const DRAFT_ID = "draft";

export type InvestigationSection =
  | "si"
  | "overview"
  | "model"
  | "data"
  | "experiments"
  | "analysis"
  | "validation"
  | "evidence";

export type ProjectSection = "overview" | "investigations" | "data" | "models" | "experiments" | "evidence";

/** Investigation navigation. Conceptual order: SI, Overview, Model, Data, Experiments, Analysis, Validation, Evidence. */
export const INVESTIGATION_SECTIONS: { id: InvestigationSection; label: string }[] = [
  { id: "si", label: "SI" },
  { id: "overview", label: "Overview" },
  { id: "model", label: "Model" },
  { id: "data", label: "Data" },
  { id: "experiments", label: "Experiments" },
  { id: "analysis", label: "Analysis" },
  { id: "validation", label: "Validation" },
  { id: "evidence", label: "Evidence" },
];

/**
 * Project Library: everything that exists in this project (as opposed to an
 * investigation, which is everything relevant to one scientific question).
 */
export const LIBRARY_SECTIONS: { id: Extract<ProjectSection, "data" | "models" | "experiments" | "evidence">; label: string }[] = [
  { id: "data", label: "Data" },
  { id: "models", label: "Models" },
  { id: "experiments", label: "Experiments" },
  { id: "evidence", label: "Evidence" },
];

export const paths = {
  project: (projectId: string) => `/projects/${projectId}`,
  projectSection: (projectId: string, section: Exclude<ProjectSection, "overview">) =>
    `/projects/${projectId}/${section}`,
  investigation: (projectId: string, investigationId: string, rest = "") =>
    `/projects/${projectId}/investigations/${investigationId}${rest ? `/${rest}` : ""}`,
};

export interface ParsedRoute {
  projectId: string | null;
  /** Project-level section, or "overview" for /projects/:id. */
  projectSection: ProjectSection | null;
  investigationId: string | null;
  investigationSection: InvestigationSection | null;
  /** Segments after the investigation section, e.g. ["sensitivity"]. */
  sub: string[];
}

export function parseRoute(pathname: string): ParsedRoute {
  const parts = pathname.split("/").filter(Boolean);
  const empty: ParsedRoute = {
    projectId: null,
    projectSection: null,
    investigationId: null,
    investigationSection: null,
    sub: [],
  };
  if (parts[0] !== "projects" || !parts[1]) return empty;
  const projectId = parts[1];
  const rest = parts.slice(2);
  if (rest.length === 0) return { ...empty, projectId, projectSection: "overview" };
  const [head, id, section, ...sub] = rest;
  if (head === "investigations") {
    if (!id) return { ...empty, projectId, projectSection: "investigations" };
    const known = INVESTIGATION_SECTIONS.some((item) => item.id === section);
    return {
      projectId,
      projectSection: "investigations",
      investigationId: id,
      investigationSection: known ? (section as InvestigationSection) : null,
      sub,
    };
  }
  if (head === "data" || head === "models" || head === "experiments" || head === "evidence") {
    return { ...empty, projectId, projectSection: head };
  }
  return { ...empty, projectId };
}

export function useRoute(): ParsedRoute {
  return parseRoute(usePathname() ?? "/");
}
