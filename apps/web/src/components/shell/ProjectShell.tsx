"use client";

import type { ReactNode } from "react";

import { InlineLoading, InlineNotification } from "@carbon/react";

import { Diagnostics } from "@/components/Diagnostics";
import { EmptyState } from "@/components/page/Page";
import { AppShell } from "@/components/shell/AppShell";
import { NavLink } from "@/components/shell/NavLink";
import { WorkspaceProvider, useWorkspace } from "@/components/workspace/WorkspaceProvider";
import type { DrwClient } from "@/lib/client";
import { paths, useRoute } from "@/lib/routes";

function ProjectGate({ children }: { children: ReactNode }) {
  const ws = useWorkspace();
  const known = ws.projects.some((project) => project.project_id === ws.projectId);

  if (!ws.projectsLoaded) {
    return (
      <div className="drw-page">
        <InlineLoading description="Loading project" />
      </div>
    );
  }
  if (!known) {
    const first = ws.projects[0];
    return (
      <div className="drw-page">
        <EmptyState
          title="Project not found"
          testId="project-not-found"
          action={
            first ? (
              <NavLink href={paths.project(first.project_id)} className="si-link">
                Open {first.name}
              </NavLink>
            ) : null
          }
        >
          No project with id <span className="drw-mono">{ws.projectId}</span> exists in this
          workspace.
        </EmptyState>
      </div>
    );
  }
  return (
    <>
      {ws.errorMessage ? (
        <div className="drw-page drw-stack-tight drw-errorbar">
          <div data-testid="error-message">
            <InlineNotification
              kind="error"
              lowContrast
              title="Request failed"
              subtitle={ws.errorMessage}
              onCloseButtonClick={ws.clearError}
            />
          </div>
          {ws.errorDiagnostics.length > 0 ? <Diagnostics diagnostics={ws.errorDiagnostics} /> : null}
        </div>
      ) : null}
      {children}
    </>
  );
}

/** Layout for everything under /projects/:projectId. */
export function ProjectShell({ client, children }: { client?: DrwClient; children: ReactNode }) {
  const route = useRoute();
  if (!route.projectId) return null;
  return (
    <WorkspaceProvider key={route.projectId} client={client} projectId={route.projectId}>
      <AppShell>
        <ProjectGate>{children}</ProjectGate>
      </AppShell>
    </WorkspaceProvider>
  );
}
