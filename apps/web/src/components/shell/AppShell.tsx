"use client";

import { forwardRef, useEffect, useId, useMemo, useState, type ReactNode } from "react";

import { useRouter } from "next/navigation";

import {
  Asleep,
  Chemistry,
  Cube,
  DataBase,
  Help,
  Home,
  Light,
  Microscope,
  Report,
  Search as SearchIcon,
  Settings,
} from "@carbon/icons-react";
import {
  ContentSwitcher,
  Header,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderMenuButton,
  HeaderName,
  Popover,
  PopoverContent,
  Search,
  SideNav,
  SideNavItems,
  SideNavLink,
  SkipToContent,
  Switch,
  Theme,
} from "@carbon/react";

import { ProjectSwitcher } from "@/components/shell/ProjectSwitcher";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { LIBRARY_SECTIONS, paths, useRoute, type ProjectSection } from "@/lib/routes";

const NAV_ITEMS: { id: ProjectSection; label: string; icon: typeof Home }[] = [
  { id: "overview", label: "Overview", icon: Home },
  { id: "investigations", label: "Investigations", icon: Microscope },
];

const LIBRARY_ICONS: Record<string, typeof Home> = {
  data: DataBase,
  models: Cube,
  experiments: Chemistry,
  evidence: Report,
};

type SearchItem = {
  key: string;
  kind: "Investigation" | "Model" | "Project";
  label: string;
  meta?: string;
  onSelect: () => void;
};

/** Anchor that routes client-side; lets Carbon's SideNavLink render a real link. */
const RouterAnchor = forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(
  function RouterAnchor({ href, onClick, ...rest }, ref) {
    const router = useRouter();
    return (
      <a
        {...rest}
        ref={ref}
        href={href}
        onClick={(event) => {
          onClick?.(event);
          if (
            event.defaultPrevented ||
            !href ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
          ) {
            return;
          }
          event.preventDefault();
          router.push(href);
        }}
      />
    );
  },
);

function HeaderSearch({ items }: { items: SearchItem[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const panelId = useId();

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const pool = needle
      ? items.filter((item) => `${item.label} ${item.meta ?? ""}`.toLowerCase().includes(needle))
      : items;
    return pool.slice(0, 8);
  }, [items, query]);

  return (
    <Popover open={open} align="bottom-end" onRequestClose={() => setOpen(false)} dropShadow>
      <HeaderGlobalAction
        aria-label="Search project"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        isActive={open}
        onClick={() => setOpen(!open)}
        tooltipAlignment="end"
      >
        <SearchIcon size={20} />
      </HeaderGlobalAction>
      <PopoverContent>
        <div className="drw-popbody" id={panelId} role="dialog" aria-label="Search">
          <Search
            size="sm"
            labelText="Search investigations, models and projects"
            placeholder="Search investigations, models, projects"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
          />
          {matches.length === 0 ? (
            <p className="drw-hint">No matches.</p>
          ) : (
            <ul className="drw-popbody__list">
              {matches.map((item) => (
                <li key={item.key}>
                  <button
                    type="button"
                    className="drw-popbody__result"
                    onClick={() => {
                      setOpen(false);
                      item.onSelect();
                    }}
                  >
                    <span>{item.label}</span>
                    <span className="drw-popbody__meta">
                      {item.kind}
                      {item.meta ? ` · ${item.meta}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="drw-hint">Ctrl K to open</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function HeaderHelp() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <Popover open={open} align="bottom-end" onRequestClose={() => setOpen(false)} dropShadow>
      <HeaderGlobalAction
        aria-label="How DRW works"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        isActive={open}
        onClick={() => setOpen(!open)}
        tooltipAlignment="end"
      >
        <Help size={20} />
      </HeaderGlobalAction>
      <PopoverContent>
        <div className="drw-popbody" id={panelId} role="dialog" aria-label="How DRW works">
          <dl className="drw-help">
            <dt>Project &amp; Library</dt>
            <dd>
              A project is a body of work. Its <strong>Library</strong> holds everything that exists
              in it: data, models, experiments and evidence.
            </dd>
            <dt>Investigation</dt>
            <dd>
              One scientific question: the model and data it uses, the experiments, the analysis,
              and the evidence that answers it.
            </dd>
            <dt>SI &mdash; Scientific Intelligence</dt>
            <dd>
              Turns a research question into a proposed, inspectable workflow. SI proposes; the
              user decides. Nothing runs without your approval.
            </dd>
            <dt>Manual</dt>
            <dd>
              The direct scientific controls behind an SI proposal: parameters, bounds, data,
              mapping, objective, optimizer and budget.
            </dd>
            <dt>Evaluation, calibration, validation</dt>
            <dd>
              Evaluation compares a run with observations. Calibration fits parameters to that
              comparison. Validation tests the calibrated model, with its parameters frozen,
              against independent observations that were not used to fit it.
            </dd>
            <dt>Evidence</dt>
            <dd>Every result is tied to the specification, seed and environment that produced it.</dd>
          </dl>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function HeaderSettings() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const { environment } = useWorkspace();
  const entries = Object.entries(environment?.environment ?? {});
  return (
    <Popover open={open} align="bottom-end" onRequestClose={() => setOpen(false)} dropShadow>
      <HeaderGlobalAction
        aria-label="Settings"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        isActive={open}
        onClick={() => setOpen(!open)}
        tooltipAlignment="end"
      >
        <Settings size={20} />
      </HeaderGlobalAction>
      <PopoverContent>
        <div className="drw-popbody" id={panelId} role="dialog" aria-label="Settings">
          <p className="drw-popbody__heading">Execution environment</p>
          {entries.length === 0 ? (
            <p className="drw-hint">Environment unavailable.</p>
          ) : (
            <dl className="drw-envlist">
              {entries.slice(0, 8).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          )}
          {environment ? (
            <p className="drw-hint">hash {environment.environment_hash.slice(0, 12)}</p>
          ) : null}
          <p className="drw-hint">No account or sign-in: DRW runs on this workspace.</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const ws = useWorkspace();
  const route = useRoute();
  const router = useRouter();
  const { projectId } = ws;
  const [navExpanded, setNavExpanded] = useState(false);
  const activeProject = ws.projects.find((p) => p.project_id === projectId);
  const investigationId = route.investigationId;
  const siActive = route.projectSection === "overview" || route.investigationSection === "si";

  function goSi(): void {
    router.push(
      investigationId
        ? paths.investigation(projectId, investigationId, "si")
        : paths.project(projectId),
    );
  }

  function goManual(): void {
    router.push(
      investigationId
        ? paths.investigation(projectId, investigationId, "overview")
        : paths.projectSection(projectId, "investigations"),
    );
  }

  const searchItems: SearchItem[] = [
    ...ws.experiments.map((experiment) => ({
      key: `exp-${experiment.experiment_id}`,
      kind: "Investigation" as const,
      label: experiment.hypothesis || experiment.experiment_id,
      meta: experiment.model_id,
      onSelect: () =>
        router.push(paths.investigation(projectId, experiment.experiment_id, "overview")),
    })),
    ...ws.models.map((model) => ({
      key: `model-${model.model_id}`,
      kind: "Model" as const,
      label: model.model_id,
      meta: `v${model.version}`,
      onSelect: () => router.push(paths.projectSection(projectId, "models")),
    })),
    ...ws.projects.map((project) => ({
      key: `proj-${project.project_id}`,
      kind: "Project" as const,
      label: project.name,
      onSelect: () => ws.selectProject(project.project_id),
    })),
  ];

  return (
    <Theme theme={ws.theme} className="drw-app">
      <SkipToContent href="#main-content" />
      <Theme theme="g100">
        <Header aria-label="Differential Research Workbench">
          <HeaderMenuButton
            aria-label={navExpanded ? "Collapse navigation" : "Expand navigation"}
            isCollapsible
            isActive={navExpanded}
            onClick={() => setNavExpanded((current) => !current)}
          />
          <HeaderName href="#" prefix="DRW" onClick={(event: React.MouseEvent) => event.preventDefault()}>
            Workbench
          </HeaderName>
          <ProjectSwitcher
            projects={ws.projects}
            activeProjectId={projectId}
            activeName={activeProject?.name ?? null}
            onSelect={ws.selectProject}
            onCreate={(name) => void ws.createProject(name)}
          />
          <div className="drw-header__center">
            <ContentSwitcher
              size="sm"
              aria-label="Interface mode"
              selectedIndex={siActive ? 0 : 1}
              onChange={({ index }) => (index === 0 ? goSi() : goManual())}
            >
              <Switch name="si" text="SI" data-testid="mode-si" />
              <Switch name="manual" text="Manual" data-testid="mode-manual" />
            </ContentSwitcher>
          </div>
          <HeaderGlobalBar>
            <HeaderSearch items={searchItems} />
            <HeaderHelp />
            <HeaderGlobalAction
              aria-label={ws.theme === "g10" ? "Switch to dark theme" : "Switch to light theme"}
              onClick={ws.toggleTheme}
              tooltipAlignment="end"
            >
              {ws.theme === "g10" ? <Asleep size={20} /> : <Light size={20} />}
            </HeaderGlobalAction>
            <HeaderSettings />
          </HeaderGlobalBar>

        </Header>
      </Theme>
        <SideNav
          aria-label="Project"
          isRail
          expanded={navExpanded}
          onToggle={((_event: unknown, value: boolean) => setNavExpanded(value)) as never}
          onOverlayClick={() => setNavExpanded(false)}
        >
          <SideNavItems>
            {NAV_ITEMS.map(({ id, label, icon }) => (
              <SideNavLink
                key={id}
                as={RouterAnchor}
                href={
                  id === "overview" ? paths.project(projectId) : paths.projectSection(projectId, id)
                }
                renderIcon={icon}
                isActive={route.projectSection === id && (id !== "investigations" || !investigationId)}
              >
                {label}
              </SideNavLink>
            ))}
            <li className="drw-navgroup" aria-hidden="true">
              Library
            </li>
            {LIBRARY_SECTIONS.map(({ id, label }) => (
              <SideNavLink
                key={id}
                as={RouterAnchor}
                href={paths.projectSection(projectId, id)}
                renderIcon={LIBRARY_ICONS[id]}
                isActive={route.projectSection === id}
              >
                {label}
              </SideNavLink>
            ))}
          </SideNavItems>
        </SideNav>

      <main id="main-content" className="drw-content">
        {children}
      </main>
    </Theme>
  );
}
