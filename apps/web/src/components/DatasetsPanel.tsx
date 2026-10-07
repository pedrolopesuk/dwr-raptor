"use client";

import { useCallback, useEffect, useState } from "react";

import { Button, InlineNotification, Table, TableBody, TableCell, TableContainer, TableHead, TableHeader, TableRow, Tag } from "@carbon/react";

import { Section } from "@/components/Section";
import { ApiError, type DrwClient } from "@/lib/client";
import type { DatasetDetail, DatasetSummary } from "@/lib/types";

/**
 * Stored datasets (M11C): a deterministic list, a detail view (schema, variables,
 * units, uncertainty, provenance, content hash, verification state) and an
 * explicit, read-only verification action.
 */
export function DatasetsPanel({
  client,
  refreshToken = 0,
}: {
  client: DrwClient;
  refreshToken?: number;
}) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setDatasets(await client.listDatasets());
    } catch {
      setDatasets([]);
    }
  }, [client]);

  useEffect(() => {
    void reload();
  }, [reload, refreshToken]);

  async function open(datasetId: string): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      setDetail(await client.describeDataset(datasetId));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
      setDetail(null);
    } finally {
      setBusy(false);
    }
  }

  async function verify(datasetId: string): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const verification = await client.verifyDataset(datasetId);
      setDetail((current) => (current && current.ref.dataset_id === datasetId ? { ...current, verification } : current));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      id="datasets-heading"
      title="Datasets"
      description="Stored scientific datasets. Each dataset has a unique fingerprint (a content hash) you can use to verify it has not changed."
    >
      <div className="drw-stack-tight" data-testid="datasets-panel">
        {error ? (
          <div data-testid="datasets-error">
            <InlineNotification kind="error" lowContrast hideCloseButton title="Datasets" subtitle={error} />
          </div>
        ) : null}

        {datasets.length === 0 ? (
          <p className="drw-muted" data-testid="datasets-empty">
            No datasets yet. Import a CSV above.
          </p>
        ) : (
          <TableContainer title={`${datasets.length} dataset(s)`}>
            <Table aria-label="Datasets" size="sm" data-testid="datasets-list">
              <TableHead>
                <TableRow>
                  <TableHeader>dataset id</TableHeader>
                  <TableHeader>name</TableHeader>
                  <TableHeader>created</TableHeader>
                  <TableHeader>hash</TableHeader>
                  <TableHeader>source</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {datasets.map((dataset) => (
                  <TableRow
                    key={dataset.dataset_id}
                    onClick={() => void open(dataset.dataset_id)}
                    data-testid={`dataset-row-${dataset.dataset_id}`}
                  >
                    <TableCell className="drw-mono">{dataset.dataset_id}</TableCell>
                    <TableCell>{dataset.name}</TableCell>
                    <TableCell>{dataset.created_at ?? "—"}</TableCell>
                    <TableCell className="drw-mono">{dataset.content_hash.slice(0, 12)}…</TableCell>
                    <TableCell>{dataset.source_kind ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {detail ? (
          <div className="drw-stack-tight" data-testid="dataset-detail">
            <div className="drw-row drw-row--center">
              <Tag type={detail.verification.ok ? "green" : "red"}>
                {detail.verification.ok ? "verified" : "verification failed"}
              </Tag>
              <span className="drw-muted" data-testid="dataset-detail-ref">
                {detail.ref.dataset_id} · {detail.ref.name} · {detail.ref.content_hash}
              </span>
              <Button
                kind="ghost"
                size="sm"
                onClick={() => void verify(detail.ref.dataset_id)}
                disabled={busy}
                data-testid="dataset-verify"
              >
                Verify
              </Button>
            </div>

            <p className="drw-muted">
              provenance: source_kind {detail.dataset.provenance.source_kind} · adapter{" "}
              {detail.dataset.provenance.adapter?.id ?? "—"} v
              {detail.dataset.provenance.adapter?.version ?? "—"} · imported{" "}
              {detail.dataset.provenance.imported_at} · file{" "}
              {detail.dataset.provenance.original_filename ?? "—"}
            </p>

            <TableContainer title="Variables">
              <Table aria-label="Dataset variables" size="sm" data-testid="dataset-variables">
                <TableHead>
                  <TableRow>
                    <TableHeader>name</TableHeader>
                    <TableHeader>kind</TableHeader>
                    <TableHeader>role</TableHeader>
                    <TableHeader>unit</TableHeader>
                    <TableHeader>depends_on</TableHeader>
                    <TableHeader>uncertainty</TableHeader>
                    <TableHeader>quality</TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {detail.dataset.observation_set.variables.map((variable) => (
                    <TableRow key={variable.name}>
                      <TableCell className="drw-mono">{variable.name}</TableCell>
                      <TableCell>{variable.kind}</TableCell>
                      <TableCell>{variable.role}</TableCell>
                      <TableCell>{variable.unit ?? "(unspecified)"}</TableCell>
                      <TableCell>{variable.depends_on.join(", ") || "—"}</TableCell>
                      <TableCell>{variable.uncertainty ? variable.uncertainty.type : "—"}</TableCell>
                      <TableCell>{variable.quality ? variable.quality.flag_column : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <div data-testid="dataset-verification">
              {detail.verification.checks.map((check) => (
                <p key={check.name} className="drw-hint">
                  [{check.status}] {check.name}
                  {check.message ? ` — ${check.message}` : ""}
                </p>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </Section>
  );
}
