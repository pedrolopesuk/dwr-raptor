"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { InlineLoading } from "@carbon/react";

import { StartExperiment } from "@/components/ExperimentsSidebar";
import { EmptyState } from "@/components/page/Page";
import { NavLink } from "@/components/shell/NavLink";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { DRAFT_ID, INVESTIGATION_SECTIONS, paths, useRoute } from "@/lib/routes";

/**
 * Layout for /projects/:projectId/investigations/:investigationId/*.
 *
 * Contextual navigation: once inside an investigation this is the primary
 * navigation. It also makes sure the investigation's stored experiment is loaded.
 */
export function InvestigationFrame({ children }: { children: ReactNode }) {
  const ws = useWorkspace();
  const route = useRoute();
  const id = route.investigationId ?? DRAFT_ID;
  const isDraft = id === DRAFT_ID;
  const attempted = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (isDraft || ws.activeId === id || attempted.current.has(id)) return;
    attempted.current.add(id);
    void ws.openInvestigation(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, isDraft, ws.activeId]);

  const section = route.investigationSection;
  const loaded = isDraft ? ws.hasDraft : ws.activeId === id;
  const title = loaded
    ? ws.hypothesis || (isDraft ? "Untitled investigation" : id)
    : isDraft
      ? "New investigation"
      : id;

  let body: ReactNode;
  if (!loaded && isDraft && section === "si") {
    body = children;
  } else if (!loaded && isDraft) {
    body = (
      <div className="drw-page drw-stack">
        <EmptyState
          title="No investigation in progress"
          testId="no-draft"
        >
          Pick a model to start a new investigation. It begins as an unsaved draft and becomes a
          stored experiment when you run it.
        </EmptyState>
        <StartExperiment
          models={ws.models}
          modelCapabilities={ws.capabilitiesById}
          selectedModelId={ws.selectedModelId}
          startingExperiment={ws.startingExperiment}
          onOpenSample={() => void ws.openSample()}
          onSelectModel={ws.setSelectedModelId}
          onStartExperiment={(modelId) => void ws.startInvestigation(modelId)}
        />
      </div>
    );
  } else if (!loaded && ws.loadingInvestigation) {
    body = (
      <div className="drw-page">
        <InlineLoading description="Loading investigation" />
      </div>
    );
  } else if (!loaded) {
    body = (
      <div className="drw-page">
        {ws.errorMessage ? (
          <EmptyState title="This investigation could not be opened" testId="investigation-unavailable">
            See the error above. The stored experiment may have been removed.
          </EmptyState>
        ) : (
          <InlineLoading description="Loading investigation" />
        )}
      </div>
    );
  } else {
    body = children;
  }

  return (
    <div className="drw-inv" data-testid="investigation-frame">
      <div className="drw-inv__bar">
        <nav className="drw-crumbs" aria-label="Breadcrumb">
          <NavLink href={paths.project(ws.projectId)}>
            {ws.projects.find((p) => p.project_id === ws.projectId)?.name ?? "Project"}
          </NavLink>
          <span aria-hidden="true">/</span>
          <NavLink href={paths.projectSection(ws.projectId, "investigations")}>Investigations</NavLink>
          <span aria-hidden="true">/</span>
          <span className="drw-crumbs__here" title={title}>
            {title}
          </span>
        </nav>
        <nav className="drw-invnav" aria-label="Investigation">
          <span className="drw-invnav__mode">{section === "si" ? "SI" : "Manual"}</span>
          {INVESTIGATION_SECTIONS.map((item) => (
            <NavLink
              key={item.id}
              href={paths.investigation(ws.projectId, id, item.id)}
              current={section === item.id}
              className="drw-invnav__item"
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="drw-inv__body">{body}</div>
    </div>
  );
}
