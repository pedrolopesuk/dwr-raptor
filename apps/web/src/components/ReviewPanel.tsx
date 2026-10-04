"use client";

import { useEffect, useState } from "react";

import { Play, StopOutline } from "@carbon/icons-react";
import { Button, TextInput } from "@carbon/react";

import { Section } from "@/components/Section";
import type { ExperimentSpec, RunEstimate } from "@/lib/types";

/** Numeric field with a local text draft so it can be cleared and retyped. */
function TimeoutField({
  value,
  onChange,
}: {
  value: number;
  onChange: (seconds: number) => void;
}) {
  const [text, setText] = useState(() => String(value));
  useEffect(() => {
    const parsed = Number(text);
    if (!(Number.isFinite(parsed) && parsed === value)) setText(String(value));
    // `text` intentionally excluded: it would clobber in-progress typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <TextInput
      id="execution-timeout"
      labelText="Execution timeout per run (seconds)"
      helperText="Enforced by the isolated runner. Not a security sandbox."
      value={text}
      onChange={(event) => {
        const next = event.target.value;
        setText(next);
        const parsed = Number(next);
        if (next.trim() !== "" && Number.isFinite(parsed) && parsed > 0) onChange(parsed);
      }}
    />
  );
}

export function ReviewPanel({
  spec,
  estimate,
  clientErrors,
  canRun,
  running,
  timeoutS,
  onTimeoutChange,
  onRun,
  onCancel,
}: {
  spec: ExperimentSpec;
  estimate: RunEstimate | null;
  clientErrors: string[];
  canRun: boolean;
  running: boolean;
  timeoutS: number;
  onTimeoutChange: (seconds: number) => void;
  onRun: () => void;
  onCancel: () => void;
}) {
  const isolation = spec.execution?.isolation ?? "subprocess";
  const payload = JSON.stringify(spec, null, 2);

  return (
    <Section
      id="review-heading"
      title="Review before running"
      description="Nothing is executed until you press Run. The plan is shown exactly as it will be sent to the Python engine."
    >
      <div className="drw-stack">
        {clientErrors.length > 0 ? (
          <ul className="drw-stack-tight" aria-label="Input problems">
            {clientErrors.map((message) => (
              <li key={message} className="drw-error-text">
                {message}
              </li>
            ))}
          </ul>
        ) : null}

        <dl className="drw-kv drw-kv--stat">
          <div>
            <dt>Estimated runs</dt>
            <dd data-testid="estimate-runs">{estimate ? estimate.total_runs : "validate first"}</dd>
          </div>
          <div>
            <dt>Sampling</dt>
            <dd>{estimate ? estimate.method : "—"}</dd>
          </div>
          <div>
            <dt>Execution isolation</dt>
            <dd data-testid="isolation">{isolation}</dd>
          </div>
          <div>
            <dt>Interventions</dt>
            <dd>{spec.factors?.length ?? 0}</dd>
          </div>
        </dl>

        <TimeoutField value={timeoutS} onChange={onTimeoutChange} />

        <div>
          <h3 className="drw-subheading">ExperimentSpec (exact payload)</h3>
          {/*
            Justified custom component: Carbon's CodeSnippet renders a scrollable
            <pre> that is not keyboard-focusable (axe: scrollable-region-focusable).
            This read-only preview is focusable so it can be scrolled with a keyboard.
          */}
          <pre className="drw-pre" data-testid="spec-preview" tabIndex={0} aria-label="ExperimentSpec">
            {payload}
          </pre>
        </div>

        <div className="drw-row drw-row--center">
          <Button
            renderIcon={Play}
            onClick={onRun}
            disabled={!canRun || running}
            data-testid="run-button"
          >
            {running ? "Running..." : "Run experiment"}
          </Button>
          {running ? (
            <Button
              kind="danger--tertiary"
              renderIcon={StopOutline}
              onClick={onCancel}
              data-testid="cancel-button"
            >
              Cancel
            </Button>
          ) : null}
        </div>
        {!canRun && !running ? (
          <p className="drw-hint" data-testid="run-blocked">
            Validate the experiment successfully to enable running.
          </p>
        ) : null}
      </div>
    </Section>
  );
}
