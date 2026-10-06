"use client";

import { Launch } from "@carbon/icons-react";
import { Button } from "@carbon/react";

import { NewExperimentPanel } from "@/components/NewExperimentPanel";
import { Section } from "@/components/Section";
import type { ModelCapabilities, ModelSummary } from "@/lib/types";

/** Start a new investigation: pick a registered model, or load the predator-prey sample. */
export function StartExperiment({
  models,
  modelCapabilities,
  selectedModelId,
  startingExperiment,
  onOpenSample,
  onSelectModel,
  onStartExperiment,
}: {
  models: ModelSummary[];
  modelCapabilities: Record<string, ModelCapabilities>;
  selectedModelId: string;
  startingExperiment: boolean;
  onOpenSample: () => void;
  onSelectModel: (modelId: string) => void;
  onStartExperiment: (modelId: string) => void;
}) {
  return (
    <Section
      id="start-experiment-heading"
      title="New investigation"
      description="Pick a registered model, or load the predator-prey sample. You start from a demonstration configuration and refine it."
    >
      <div className="drw-stack-tight drw-select-narrow">
        <NewExperimentPanel
          models={models}
          capabilities={modelCapabilities}
          selectedModelId={selectedModelId}
          onSelectModel={onSelectModel}
          onStart={onStartExperiment}
          starting={startingExperiment}
        />
        <div>
          <Button data-testid="open-sample" renderIcon={Launch} onClick={onOpenSample}>
            Open sample project (predator-prey)
          </Button>
        </div>
      </div>
    </Section>
  );
}
