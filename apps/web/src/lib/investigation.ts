import type { StateKind } from "@/components/page/Page";
import type { ExperimentSummary } from "@/lib/types";

/** The question an investigation addresses is its experiment's hypothesis. */
export function investigationTitle(experiment: ExperimentSummary): string {
  return experiment.hypothesis.trim() || experiment.name.trim() || experiment.experiment_id;
}

/** Stage derived only from what the stored experiment records. */
export function investigationStage(experiment: ExperimentSummary): {
  kind: StateKind;
  label: string;
} {
  if (experiment.n_failed > 0) return { kind: "failed", label: "Run incomplete" };
  if (experiment.n_runs > 0 && experiment.n_succeeded === experiment.n_runs) {
    return { kind: "done", label: "Baseline run completed" };
  }
  return { kind: "pending", label: "Not run" };
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function newestFirst(items: ExperimentSummary[]): ExperimentSummary[] {
  return [...items].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
}
