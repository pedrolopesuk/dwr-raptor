import { render, type RenderResult } from "@testing-library/react";

import { InvestigationFrame } from "@/components/shell/InvestigationFrame";
import { InvestigationIndexRedirect } from "@/components/shell/InvestigationIndexRedirect";
import { ProjectShell } from "@/components/shell/ProjectShell";
import type { DrwClient } from "@/lib/client";
import { useRoute } from "@/lib/routes";
import {
  InvestigationAnalysisView,
  InvestigationEvidenceView,
  InvestigationExperimentsView,
  InvestigationModelView,
  InvestigationOverviewView,
  InvestigationSiView,
  InvestigationValidationView,
} from "@/views/investigation";
import {
  DataView,
  InvestigationsIndexView,
  ProjectEvidenceView,
  ProjectExperimentsView,
  ProjectModelsView,
  ProjectOverviewView,
} from "@/views/project";

import { __setPath } from "./next-navigation";

/** Mirrors the file-based route table under src/app/projects. */
function RouteView() {
  const route = useRoute();

  if (route.investigationId) {
    let page;
    switch (route.investigationSection) {
      case "si":
        page = <InvestigationSiView />;
        break;
      case "overview":
        page = <InvestigationOverviewView />;
        break;
      case "data":
        page = <DataView scope="investigation" />;
        break;
      case "model":
        page = <InvestigationModelView />;
        break;
      case "experiments":
        page = <InvestigationExperimentsView />;
        break;
      case "analysis":
        page = <InvestigationAnalysisView />;
        break;
      case "validation":
        page = <InvestigationValidationView />;
        break;
      case "evidence":
        page = <InvestigationEvidenceView />;
        break;
      default:
        page = <InvestigationIndexRedirect />;
    }
    return <InvestigationFrame>{page}</InvestigationFrame>;
  }

  switch (route.projectSection) {
    case "investigations":
      return <InvestigationsIndexView />;
    case "data":
      return <DataView scope="project" />;
    case "models":
      return <ProjectModelsView />;
    case "experiments":
      return <ProjectExperimentsView />;
    case "evidence":
      return <ProjectEvidenceView />;
    default:
      return <ProjectOverviewView />;
  }
}

export function renderApp(client: DrwClient, path = "/projects/default"): RenderResult {
  __setPath(path);
  return render(
    <ProjectShell client={client}>
      <RouteView />
    </ProjectShell>,
  );
}
