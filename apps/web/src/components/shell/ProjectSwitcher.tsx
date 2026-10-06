"use client";

import { useEffect, useId, useMemo, useState } from "react";

import { Add, ChevronDown } from "@carbon/icons-react";
import { Button, Popover, PopoverContent, Search, TextInput } from "@carbon/react";

import type { Project } from "@/lib/types";

/**
 * Header project switcher: recent projects, search, and new project.
 * Uses the same handlers as everywhere else, so there is one source of truth.
 */
export function ProjectSwitcher({
  projects,
  activeProjectId,
  activeName,
  onSelect,
  onCreate,
}: {
  projects: Project[];
  activeProjectId: string | null;
  activeName: string | null;
  onSelect: (projectId: string) => void;
  onCreate: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const panelId = useId();

  useEffect(() => {
    if (!open) {
      setQuery("");
      setCreating(false);
      setName("");
    }
  }, [open]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? projects.filter((p) => p.name.toLowerCase().includes(needle)) : projects;
  }, [projects, query]);

  return (
    <Popover open={open} align="bottom-start" onRequestClose={() => setOpen(false)} dropShadow>
      <Button
        kind="ghost"
        size="md"
        renderIcon={ChevronDown}
        className="drw-project"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        data-testid="project-switcher"
        onClick={() => setOpen(!open)}
      >
        <span className="drw-project__label">Project</span>
        <span className="drw-project__name">{activeName ?? "No project"}</span>
      </Button>
      <PopoverContent>
        <div className="drw-popbody" id={panelId} role="dialog" aria-label="Switch project">
          <Search
            size="sm"
            labelText="Search projects"
            placeholder="Search projects"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
          />
          <p className="drw-popbody__heading">Recent projects</p>
          {visible.length === 0 ? (
            <p className="drw-hint">No projects match.</p>
          ) : (
            <ul className="drw-popbody__list">
              {visible.map((project) => (
                <li key={project.project_id}>
                  <Button
                    kind="ghost"
                    size="sm"
                    className="drw-popbody__item"
                    aria-current={project.project_id === activeProjectId ? "true" : undefined}
                    onClick={() => {
                      onSelect(project.project_id);
                      setOpen(false);
                    }}
                  >
                    {project.name}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <hr className="drw-popbody__sep" />
          {/* The button stays mounted (only hidden): removing the clicked element makes
              the popover treat the click as an outside click and close. */}
          <Button
            kind="ghost"
            size="sm"
            renderIcon={Add}
            className="drw-popbody__item"
            hidden={creating}
            onClick={() => setCreating(true)}
          >
            New project
          </Button>
          {creating ? (
            <form
              className="drw-popbody__create"
              onSubmit={(event) => {
                event.preventDefault();
                if (name.trim().length === 0) return;
                onCreate(name.trim());
                setOpen(false);
              }}
            >
              <TextInput
                id={`${panelId}-new`}
                size="sm"
                labelText="New project name"
                hideLabel
                placeholder="Project name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                // eslint-disable-next-line jsx-a11y/no-autofocus
                autoFocus
              />
              <Button type="submit" size="sm" disabled={name.trim().length === 0}>
                Create
              </Button>
            </form>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
