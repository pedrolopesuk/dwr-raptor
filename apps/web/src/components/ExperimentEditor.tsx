"use client";

import { useEffect, useState } from "react";

import { Add, TrashCan } from "@carbon/icons-react";
import { Button, FormGroup, Select, SelectItem, TextArea, TextInput } from "@carbon/react";

import { Section } from "@/components/Section";
import { newFactorDraft, type BaselineValue, type FactorDraft } from "@/lib/experiment";
import { formatScalar } from "@/lib/format";
import type { ModelParameter, ModelSchema } from "@/lib/types";

const NUMERIC_TYPES = new Set(["float", "int"]);

/** Numeric field with a local text draft so it can be cleared and retyped. */
function NumericDraftField({
  id,
  labelText,
  helperText,
  value,
  onChange,
}: {
  id: string;
  labelText: string;
  helperText?: string;
  value: BaselineValue | undefined;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(() => (value === undefined ? "" : String(value)));

  useEffect(() => {
    if (value === undefined) return;
    const parsed = Number(text);
    if (!(Number.isFinite(parsed) && parsed === value)) setText(String(value));
    // `text` intentionally excluded: it would clobber in-progress typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <TextInput
      id={id}
      labelText={labelText}
      helperText={helperText}
      value={text}
      onChange={(event) => {
        const next = event.target.value;
        setText(next);
        const parsed = Number(next);
        if (next.trim() !== "" && Number.isFinite(parsed)) onChange(parsed);
      }}
    />
  );
}

export function ExperimentEditor({
  schema,
  hypothesis,
  onHypothesisChange,
  baseline,
  onBaselineChange,
  factors,
  onFactorsChange,
}: {
  schema: ModelSchema;
  hypothesis: string;
  onHypothesisChange: (value: string) => void;
  baseline: Record<string, BaselineValue>;
  onBaselineChange: (name: string, value: BaselineValue) => void;
  factors: FactorDraft[];
  onFactorsChange: (factors: FactorDraft[]) => void;
}) {
  const numericParameters = schema.parameters.filter((p) => NUMERIC_TYPES.has(p.type));

  function updateFactor(id: string, patch: Partial<FactorDraft>): void {
    onFactorsChange(factors.map((f) => (f.id === id ? { ...f, ...patch } : f)));
  }

  function addFactor(): void {
    const first = numericParameters[0];
    if (!first) return;
    const defaultLow = first.lower ?? 0;
    const defaultHigh = first.upper ?? 1;
    onFactorsChange(
      factors.concat(
        newFactorDraft(first.name, String(defaultLow + (defaultHigh - defaultLow) * 0.1)),
      ),
    );
  }

  return (
    <Section
      id="config-heading"
      title="Experiment"
      description="State the hypothesis, review the baseline conditions, and define the intervention(s)."
    >
      <div className="drw-stack">
        <TextArea
          id="hypothesis"
          labelText="Hypothesis"
          rows={3}
          value={hypothesis}
          onChange={(event) => onHypothesisChange(event.target.value)}
        />

        <FormGroup legendText="Baseline conditions (frozen reference)">
          <div className="drw-fields">
            {schema.parameters.map((param) => (
              <BaselineField
                key={param.name}
                param={param}
                value={baseline[param.name]}
                onChange={(value) => onBaselineChange(param.name, value)}
              />
            ))}
          </div>
          <p className="drw-hint drw-form-note">
            Numeric fields accept any value; the engine rejects out-of-bounds baselines on
            validation.
          </p>
        </FormGroup>

        <FormGroup legendText="Intervention (what changes relative to the baseline)">
          <div className="drw-stack-tight">
            {numericParameters.length === 0 ? (
              <p className="drw-muted">This model has no numeric parameters to vary.</p>
            ) : null}

            {factors.map((factor) => (
              <div key={factor.id} className="drw-intervention">
                <div className="drw-row">
                  <div className="drw-grow">
                    <Select
                      id={`${factor.id}-parameter`}
                      labelText="parameter"
                      value={factor.parameter}
                      onChange={(event) =>
                        updateFactor(factor.id, { parameter: event.target.value })
                      }
                    >
                      {numericParameters.map((param) => (
                        <SelectItem
                          key={param.name}
                          value={param.name}
                          text={`${param.name} (${param.unit})`}
                        />
                      ))}
                    </Select>
                  </div>
                  <div className="drw-grow">
                    <Select
                      id={`${factor.id}-mode`}
                      labelText="mode"
                      value={factor.mode}
                      onChange={(event) =>
                        updateFactor(factor.id, {
                          mode: event.target.value as FactorDraft["mode"],
                        })
                      }
                    >
                      <SelectItem value="value" text="single value" />
                      <SelectItem value="range" text="range (grid)" />
                    </Select>
                  </div>
                  {factor.mode === "value" ? (
                    <div className="drw-grow">
                      <TextInput
                        id={`${factor.id}-value`}
                        labelText="value"
                        value={factor.value}
                        onChange={(event) => updateFactor(factor.id, { value: event.target.value })}
                      />
                    </div>
                  ) : (
                    <>
                      <div className="drw-grow">
                        <TextInput
                          id={`${factor.id}-lower`}
                          labelText="lower"
                          value={factor.lower}
                          onChange={(event) =>
                            updateFactor(factor.id, { lower: event.target.value })
                          }
                        />
                      </div>
                      <div className="drw-grow">
                        <TextInput
                          id={`${factor.id}-upper`}
                          labelText="upper"
                          value={factor.upper}
                          onChange={(event) =>
                            updateFactor(factor.id, { upper: event.target.value })
                          }
                        />
                      </div>
                      <div className="drw-grow">
                        <TextInput
                          id={`${factor.id}-steps`}
                          labelText="steps"
                          value={factor.steps}
                          onChange={(event) =>
                            updateFactor(factor.id, { steps: event.target.value })
                          }
                        />
                      </div>
                    </>
                  )}
                  <Button
                    kind="ghost"
                    hasIconOnly
                    renderIcon={TrashCan}
                    iconDescription={`Remove intervention on ${factor.parameter}`}
                    tooltipPosition="left"
                    onClick={() => onFactorsChange(factors.filter((f) => f.id !== factor.id))}
                  />
                </div>
              </div>
            ))}

            <div>
              <Button kind="tertiary" size="md" renderIcon={Add} onClick={addFactor}>
                Add intervention
              </Button>
            </div>
          </div>
        </FormGroup>
      </div>
    </Section>
  );
}

function BaselineField({
  param,
  value,
  onChange,
}: {
  param: ModelParameter;
  value: BaselineValue | undefined;
  onChange: (value: BaselineValue) => void;
}) {
  const id = `baseline-${param.name}`;
  const label = `${param.name} (${param.unit})`;
  const helper = `${param.role === "state" ? "initial condition · " : ""}baseline ${formatScalar(
    param.nominal,
  )} · bounds [${formatScalar(param.lower)}, ${formatScalar(param.upper)}]`;

  if (param.type === "bool") {
    return (
      <Select
        id={id}
        labelText={label}
        value={String(value ?? false)}
        onChange={(event) => onChange(event.target.value === "true")}
      >
        <SelectItem value="true" text="true" />
        <SelectItem value="false" text="false" />
      </Select>
    );
  }
  if (param.type === "categorical") {
    return (
      <Select
        id={id}
        labelText={label}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
      >
        {param.options.map((option) => (
          <SelectItem key={option} value={option} text={option} />
        ))}
      </Select>
    );
  }
  return (
    <NumericDraftField
      id={id}
      labelText={label}
      helperText={helper}
      value={value}
      onChange={onChange}
    />
  );
}
