"use client";

import { ArrowRight } from "@carbon/icons-react";
import { Button, InlineLoading, Select, SelectItem } from "@carbon/react";

import { modelViability } from "@/lib/experiment";
import type { ModelCapabilities, ModelSummary } from "@/lib/types";

/**
 * Model picker for starting a new experiment.
 *
 * It lists every model the Python core registers and disables any the engine
 * cannot configure, with the reason. The model list and capabilities are
 * authoritative inputs from Python; this component only decides what to show.
 */
export function NewExperimentPanel({
  models,
  capabilities,
  selectedModelId,
  onSelectModel,
  onStart,
  starting,
}: {
  models: ModelSummary[];
  capabilities: Record<string, ModelCapabilities>;
  selectedModelId: string;
  onSelectModel: (modelId: string) => void;
  onStart: (modelId: string) => void;
  starting: boolean;
}) {
  const selected = models.find((model) => model.model_id === selectedModelId);
  const viability = modelViability(selected ? capabilities[selectedModelId] : null);

  return (
    <div className="drw-stack-tight">
      {models.length === 0 ? (
        <InlineLoading description="Loading models" />
      ) : (
        <>
          <Select
            id="model-select"
            data-testid="model-select"
            labelText="Model"
            hideLabel
            value={selectedModelId}
            onChange={(event) => onSelectModel(event.target.value)}
          >
            {models.map((model) => {
              const modelEligibility = modelViability(capabilities[model.model_id]);
              return (
                <SelectItem
                  key={model.model_id}
                  value={model.model_id}
                  text={`${model.model_id} (v${model.version})`}
                  disabled={!modelEligibility.eligible}
                />
              );
            })}
          </Select>

          {selected ? (
            <p className="drw-hint" data-testid="model-summary">
              {selected.description || selected.model_id} · {selected.n_parameters} parameter(s),{" "}
              {selected.n_outputs} output(s)
            </p>
          ) : null}

          {!viability.eligible && viability.reason ? (
            <p className="drw-hint drw-error-text" data-testid="model-eligibility-note">
              {viability.reason}
            </p>
          ) : (
            <p className="drw-hint">
              Seeds a <strong>demonstration</strong> configuration (+10% on the first input), not a
              scientifically justified experiment. Technical eligibility is not scientific validity.
            </p>
          )}

          <Button
            kind="tertiary"
            size="md"
            renderIcon={ArrowRight}
            data-testid="create-experiment"
            disabled={!selectedModelId || !viability.eligible || starting}
            onClick={() => onStart(selectedModelId)}
          >
            {starting ? "Starting..." : "Create experiment"}
          </Button>
        </>
      )}
    </div>
  );
}
