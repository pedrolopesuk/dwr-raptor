"use client";

import { CheckmarkOutline } from "@carbon/icons-react";
import { Button, Tag } from "@carbon/react";

import { Diagnostics } from "@/components/Diagnostics";
import { Section } from "@/components/Section";
import type { ValidationResult } from "@/lib/types";

export function ValidationPanel({
  validation,
  clientErrors,
  validating,
  onValidate,
  canValidate,
}: {
  validation: ValidationResult | null;
  clientErrors: string[];
  validating: boolean;
  onValidate: () => void;
  canValidate: boolean;
}) {
  return (
    <Section
      id="validation-heading"
      title="Validation"
      description="Validation runs in the Python engine - the same code path as the CLI. Nothing executes here."
    >
      <div className="drw-stack-tight">
        <div>
          <Button
            renderIcon={CheckmarkOutline}
            onClick={onValidate}
            disabled={!canValidate || validating}
            data-testid="validate-button"
          >
            {validating ? "Validating..." : "Validate configuration"}
          </Button>
        </div>

        {clientErrors.length > 0 ? (
          <Diagnostics
            diagnostics={clientErrors.map((message) => ({
              level: "error" as const,
              code: "input_invalid",
              message,
            }))}
          />
        ) : null}

        {validation ? (
          <div className="drw-stack-tight">
            <div className="drw-row drw-row--center">
              <span data-testid="validation-verdict">
                <Tag type={validation.ok ? "green" : "red"}>
                  {validation.ok ? "valid" : "invalid"}
                </Tag>
              </span>
              <span className="drw-muted">
                {validation.estimate.total_runs} run(s), method {validation.estimate.method}
              </span>
            </div>
            <Diagnostics diagnostics={validation.diagnostics} />
          </div>
        ) : null}
      </div>
    </Section>
  );
}
