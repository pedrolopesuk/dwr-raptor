"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Button,
  InlineNotification,
  Select,
  SelectItem,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
  TextInput,
} from "@carbon/react";

import { Section } from "@/components/Section";
import { ApiError, type DrwClient } from "@/lib/client";
import type {
  CsvImportConfig,
  CsvInspection,
  ColumnConfig,
  DatasetImportResult,
  DatasetSource,
} from "@/lib/types";

const ROLES = ["coordinate", "measurement", "derived", "uncertainty", "quality", "metadata"];
const UNCERTAINTY_TYPES = ["none", "std", "stderr", "precision", "asymmetric"];

interface ColumnDraft {
  role: string;
  name: string;
  unit: string;
  dependsOn: string;
  uncertaintyType: string;
  uncertaintyColumns: string;
  qualityColumn: string;
}

function blankDraft(): ColumnDraft {
  return {
    role: "measurement",
    name: "",
    unit: "",
    dependsOn: "",
    uncertaintyType: "none",
    uncertaintyColumns: "",
    qualityColumn: "",
  };
}

function draftFromInspection(column: { column: string; suggested_role: string | null; suggested_name: string | null }): ColumnDraft {
  return {
    ...blankDraft(),
    role: column.suggested_role ?? "measurement",
    name: column.suggested_name ?? column.column,
  };
}

/**
 * CSV dataset import (M11C).
 *
 * Detected structure is advisory; the researcher assigns roles, names, units and
 * coordinate dependencies explicitly. "Validate" runs the import as a dry run (no
 * persistence); "Import" writes one immutable, content-addressed dataset.
 */
export function DatasetImportPanel({
  client,
  onImported,
}: {
  client: DrwClient;
  onImported?: () => void;
}) {
  const [sources, setSources] = useState<DatasetSource[]>([]);
  const [filename, setFilename] = useState("");
  const [missingText, setMissingText] = useState("");
  const [name, setName] = useState("");
  const [inspection, setInspection] = useState<CsvInspection | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ColumnDraft>>({});
  const [result, setResult] = useState<DatasetImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        setSources(await client.listDatasetSources());
      } catch {
        setSources([]);
      }
    })();
  }, [client]);

  const missingCodes = useMemo(
    () => missingText.split(",").map((item) => item.trim()).filter(Boolean),
    [missingText],
  );

  function setDraft(column: string, patch: Partial<ColumnDraft>): void {
    setDrafts((current) => ({
      ...current,
      [column]: { ...(current[column] ?? blankDraft()), ...patch },
    }));
  }

  function buildConfig(): CsvImportConfig {
    const columns: ColumnConfig[] = (inspection?.columns ?? []).map((column) => {
      const draft = drafts[column.column] ?? draftFromInspection(column);
      const config: ColumnConfig = { column: column.column, role: draft.role };
      if (draft.name && draft.name !== column.column) config.name = draft.name;
      if (draft.unit.trim()) config.unit = draft.unit.trim();
      const depends = draft.dependsOn.split(",").map((item) => item.trim()).filter(Boolean);
      if (depends.length > 0) config.depends_on = depends;
      if (draft.role === "measurement" && draft.uncertaintyType !== "none") {
        const refs = draft.uncertaintyColumns.split(",").map((item) => item.trim()).filter(Boolean);
        if (draft.uncertaintyType === "asymmetric") {
          if (refs.length >= 2) {
            config.uncertainty = { type: "asymmetric", lower_column: refs[0], upper_column: refs[1] };
          }
        } else if (refs.length >= 1) {
          config.uncertainty = { type: draft.uncertaintyType as "std", column: refs[0] };
        }
      }
      if (draft.role === "measurement" && draft.qualityColumn.trim()) {
        config.quality = { flag_column: draft.qualityColumn.trim() };
      }
      return config;
    });
    return {
      name: name || filename.replace(/\.csv$/i, "") || "dataset",
      missing_codes: missingCodes,
      columns,
    };
  }

  async function inspect(): Promise<void> {
    if (!filename) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const found = await client.inspectDataset(filename, { missingCodes });
      setInspection(found);
      const next: Record<string, ColumnDraft> = {};
      for (const column of found.columns) next[column.column] = draftFromInspection(column);
      setDrafts(next);
      if (!name) setName(filename.replace(/\.csv$/i, ""));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
      setInspection(null);
    } finally {
      setBusy(false);
    }
  }

  async function submit(dryRun: boolean): Promise<void> {
    if (!filename || !inspection) return;
    setBusy(true);
    setError(null);
    if (!dryRun) setResult(null);
    try {
      const imported = await client.importDataset(filename, buildConfig(), dryRun);
      setResult(imported);
      if (!dryRun) onImported?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      id="dataset-import-heading"
      title="Import a dataset (CSV)"
      description="Inspect a CSV from the local workspace, assign roles/units/coordinates/uncertainty explicitly, then import one immutable, content-addressed dataset."
    >
      <div className="drw-stack-tight" data-testid="dataset-panel">
        <p className="drw-hint" data-testid="dataset-advisory">
          Detected structure is <strong>advisory only</strong>. Roles, units, coordinates and
          uncertainty are your explicit configuration; nothing scientific is inferred from column
          names. Files live in the workspace <code>dataset-sources/</code> directory.
        </p>

        <div className="drw-importbar">
          <Select
            id="dataset-source"
            data-testid="dataset-source"
            labelText="Source CSV"
            value={filename}
            onChange={(event) => setFilename(event.target.value)}
          >
            <SelectItem value="" text="— select —" />
            {sources.map((source) => (
              <SelectItem key={source.filename} value={source.filename} text={source.filename} />
            ))}
          </Select>
          <TextInput
            id="dataset-missing"
            data-testid="dataset-missing"
            labelText="Missing codes (comma-separated)"
            helperText="cells equal to these are treated as missing"
            value={missingText}
            onChange={(event) => setMissingText(event.target.value)}
          />
          <Button size="md" onClick={() => void inspect()} disabled={!filename || busy} data-testid="dataset-inspect">
            Inspect
          </Button>
        </div>

        {error ? (
          <div data-testid="dataset-error">
            <InlineNotification kind="error" lowContrast hideCloseButton title="Dataset" subtitle={error} />
          </div>
        ) : null}

        {inspection ? (
          <>
            <p className="drw-muted" data-testid="dataset-summary">
              {inspection.filename} · delimiter {JSON.stringify(inspection.delimiter)} · header{" "}
              {String(inspection.has_header)} · rows {inspection.row_count} · columns{" "}
              {inspection.columns.length}
            </p>
            {inspection.diagnostics.map((diagnostic) => (
              <p key={`${diagnostic.code}-${diagnostic.message}`} className="drw-hint">
                [{diagnostic.level}] {diagnostic.code}: {diagnostic.message}
              </p>
            ))}

            <TableContainer title="Preview (first rows)">
              <Table aria-label="CSV preview" size="sm" data-testid="dataset-preview">
                <TableHead>
                  <TableRow>
                    {inspection.columns.map((column) => (
                      <TableHeader key={column.column}>{column.column}</TableHeader>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {inspection.preview.slice(0, 5).map((row, index) => (
                    <TableRow key={index}>
                      {inspection.columns.map((column) => (
                        <TableCell key={column.column}>{row[column.column]}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <div data-testid="dataset-columns" className="drw-stack-tight">
              <h3 className="drw-subheading">Describe each column</h3>
              {inspection.columns.map((column) => {
                const draft = drafts[column.column] ?? draftFromInspection(column);
                return (
                  <fieldset
                    key={column.column}
                    className="drw-colcard"
                    data-testid={`dataset-col-${column.column}`}
                  >
                    <legend className="drw-colcard__legend">
                      <span className="drw-mono">{column.column}</span>
                      <Tag type="gray" size="sm">
                        {column.kind}
                      </Tag>
                    </legend>
                    <div className="drw-colcard__grid">
                      <Select
                        id={`dataset-role-${column.column}`}
                        size="sm"
                        labelText="role"
                        data-testid={`dataset-role-${column.column}`}
                        value={draft.role}
                        onChange={(event) => setDraft(column.column, { role: event.target.value })}
                      >
                        {ROLES.map((role) => (
                          <SelectItem key={role} value={role} text={role} />
                        ))}
                      </Select>
                      <TextInput
                        id={`dataset-name-${column.column}`}
                        size="sm"
                        labelText="name"
                        value={draft.name}
                        onChange={(event) => setDraft(column.column, { name: event.target.value })}
                      />
                      <TextInput
                        id={`dataset-unit-${column.column}`}
                        size="sm"
                        labelText="unit"
                        value={draft.unit}
                        onChange={(event) => setDraft(column.column, { unit: event.target.value })}
                      />
                      <TextInput
                        id={`dataset-deps-${column.column}`}
                        size="sm"
                        labelText="depends on (coordinates)"
                        value={draft.dependsOn}
                        onChange={(event) => setDraft(column.column, { dependsOn: event.target.value })}
                      />
                      <Select
                        id={`dataset-unc-${column.column}`}
                        size="sm"
                        labelText="uncertainty type"
                        data-testid={`dataset-unc-${column.column}`}
                        value={draft.uncertaintyType}
                        onChange={(event) =>
                          setDraft(column.column, { uncertaintyType: event.target.value })
                        }
                      >
                        {UNCERTAINTY_TYPES.map((type) => (
                          <SelectItem key={type} value={type} text={type} />
                        ))}
                      </Select>
                      <TextInput
                        id={`dataset-unccol-${column.column}`}
                        size="sm"
                        labelText="uncertainty column(s)"
                        value={draft.uncertaintyColumns}
                        onChange={(event) =>
                          setDraft(column.column, { uncertaintyColumns: event.target.value })
                        }
                      />
                      <TextInput
                        id={`dataset-qc-${column.column}`}
                        size="sm"
                        labelText="quality flag column"
                        value={draft.qualityColumn}
                        onChange={(event) =>
                          setDraft(column.column, { qualityColumn: event.target.value })
                        }
                      />
                    </div>
                  </fieldset>
                );
              })}
            </div>

            <div className="drw-importbar drw-importbar--submit">
              <TextInput
                id="dataset-dsname"
                data-testid="dataset-dsname"
                labelText="Dataset name"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <Button size="md" kind="tertiary" onClick={() => void submit(true)} disabled={busy} data-testid="dataset-validate">
                Validate
              </Button>
              <Button size="md" onClick={() => void submit(false)} disabled={busy} data-testid="dataset-import">
                Import
              </Button>
            </div>
          </>
        ) : null}

        {result ? (
          <div className="drw-stack-tight" data-testid="dataset-result">
            <div className="drw-row drw-row--center">
              <Tag type={result.stored ? "green" : "blue"}>
                {result.stored ? "imported" : "validated"}
              </Tag>
              <span className="drw-muted">
                {result.ref.dataset_id} · {result.ref.name} · content_hash {result.ref.content_hash.slice(0, 12)}…
              </span>
            </div>
            {result.stored ? (
              <InlineNotification
                kind="success"
                lowContrast
                hideCloseButton
                title="Immutable dataset created"
                subtitle="The dataset was written and verified; its content hash is its identity."
              />
            ) : (
              <p className="drw-hint">Validation only: nothing was written.</p>
            )}
          </div>
        ) : null}
      </div>
    </Section>
  );
}
