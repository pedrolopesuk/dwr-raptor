"use client";

import { InlineLoading, ProgressBar, Tag } from "@carbon/react";

import type { UiStatus } from "@/lib/experiment";

const LABELS: Record<UiStatus, string> = {
  idle: "Idle - configure the experiment, then validate.",
  validating: "Validating the experiment with the Python engine...",
  running: "Running the experiment...",
  succeeded: "Succeeded - all runs completed.",
  failed: "Failed - at least one run did not succeed.",
  cancelled: "Cancelled - the run was stopped before completing.",
  timed_out: "Timed out - at least one run exceeded its time budget.",
};

const TAG_TYPE: Record<UiStatus, "gray" | "cool-gray" | "blue" | "green" | "red" | "magenta"> = {
  idle: "gray",
  validating: "cool-gray",
  running: "blue",
  succeeded: "green",
  failed: "red",
  cancelled: "magenta",
  timed_out: "red",
};

export function StatusBanner({
  status,
  detail,
  progress,
}: {
  status: UiStatus;
  detail?: string | null;
  progress?: { completed: number; total: number } | null;
}) {
  const busy = status === "running" || status === "validating";
  return (
    <section className="drw-status" aria-live="polite" data-testid="status-banner" aria-label="Run status">
      <div className="drw-status__bar" data-status={status}>
        <span data-testid="status-value">
          <Tag type={TAG_TYPE[status]}>{status}</Tag>
        </span>
        {busy ? (
          <InlineLoading
            description={status === "running" ? "Running" : "Validating"}
            status="active"
          />
        ) : null}
        <span className="drw-status__label">{LABELS[status]}</span>
        {detail ? <span className="drw-status__detail">{detail}</span> : null}
      </div>
      {status === "running" && progress && progress.total > 0 ? (
        <ProgressBar
          label={`${progress.completed} of ${progress.total} runs completed`}
          helperText="Measured from the run journal. No estimated percentages."
          value={progress.completed}
          max={progress.total}
        />
      ) : null}
    </section>
  );
}
