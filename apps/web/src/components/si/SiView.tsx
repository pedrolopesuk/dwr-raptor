"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ArrowUp, Attachment } from "@carbon/icons-react";
import { Button, Select, SelectItem, TextArea } from "@carbon/react";

import { useWorkspace, type SiMessage } from "@/components/workspace/WorkspaceProvider";
import type { ExperimentSpec, ModelSummary } from "@/lib/types";

export interface Suggestion {
  label: string;
  /** Text placed in the composer, or null when the action navigates instead. */
  prompt: string | null;
  href?: string;
}

export const PROJECT_SUGGESTIONS: Suggestion[] = [
  { label: "Import observations", prompt: null },
  { label: "Analyze my model", prompt: "Analyze my model: which parameters drive its outputs most?" },
  { label: "Test a hypothesis", prompt: "Test the hypothesis that " },
  { label: "Design an experiment", prompt: "Design an experiment to find out how " },
];

export const INVESTIGATION_SUGGESTIONS: Suggestion[] = [
  { label: "Analyze the model", prompt: "Analyze the model: which parameters drive its outputs most?" },
  { label: "Inspect observations", prompt: null },
  {
    label: "Check identifiability",
    prompt: "Which parameters of this model can be distinguished from one another?",
  },
  { label: "Calibrate parameters", prompt: "Calibrate the model parameters against my observations." },
  {
    label: "Validate against observations",
    prompt: "Validate the calibrated model against independent observations.",
  },
  { label: "Design an experiment", prompt: "Design an experiment to find out how " },
];

export function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  models,
  selectedModelId,
  onSelectModel,
  placeholder,
  rows,
  onAttach,
  inputRef,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
  models: ModelSummary[];
  selectedModelId: string;
  onSelectModel: (modelId: string) => void;
  placeholder: string;
  rows: number;
  onAttach: () => void;
  inputRef?: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const canSend = value.trim().length > 0 && !busy && selectedModelId !== "";

  function submit(event?: FormEvent): void {
    event?.preventDefault();
    if (canSend) onSubmit();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  }

  return (
    <form className="si-composer" onSubmit={submit} aria-label="Ask SI">
      <TextArea
        id="si-input"
        ref={inputRef}
        labelText="Ask SI"
        hideLabel
        className="si-composer__input"
        data-testid="si-input"
        rows={rows}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="si-composer__bar">
        <Button kind="ghost" size="sm" renderIcon={Attachment} type="button" onClick={onAttach}>
          Attach data
        </Button>
        <span className="si-composer__spacer" />
        <Select
          id="si-model"
          size="sm"
          inline
          labelText="Model"
          hideLabel
          value={selectedModelId}
          onChange={(event) => onSelectModel(event.target.value)}
          data-testid="si-model"
        >
          {models.length === 0 ? <SelectItem value="" text="No models" /> : null}
          {models.map((model) => (
            <SelectItem key={model.model_id} value={model.model_id} text={model.model_id} />
          ))}
        </Select>
        <Button
          type="submit"
          size="sm"
          hasIconOnly
          renderIcon={ArrowUp}
          iconDescription="Send"
          tooltipPosition="top"
          data-testid="si-send"
          disabled={!canSend}
        />
      </div>
    </form>
  );
}

export function Suggestions({
  items,
  onPick,
}: {
  items: Suggestion[];
  onPick: (item: Suggestion) => void;
}) {
  return (
    <ul className="si-suggest" aria-label="Suggested actions">
      {items.map((item) => (
        <li key={item.label}>
          <Button kind="tertiary" size="sm" onClick={() => onPick(item)}>
            {item.label}
          </Button>
        </li>
      ))}
    </ul>
  );
}

export function PlanCard({
  message,
  model,
  onReview,
  onRun,
  running,
}: {
  message: Extract<SiMessage, { kind: "plan" }>;
  model: ModelSummary | undefined;
  onReview: (spec: ExperimentSpec, modelId: string) => void;
  onRun: (spec: ExperimentSpec, modelId: string) => void;
  running: boolean;
}) {
  const { proposal, modelId } = message;
  const spec = proposal.spec;
  if (proposal.questions.length > 0 || spec === null) {
    return (
      <div className="si-plan" data-testid="si-questions">
        <p className="si-plan__lead">I need a bit more before I can propose a configuration.</p>
        <ul className="si-plan__list">
          {proposal.questions.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      </div>
    );
  }
  const steps: string[] = [];
  const baselineCount = Object.keys(spec.baseline ?? {}).length;
  steps.push(`Fix a baseline of ${baselineCount} parameter${baselineCount === 1 ? "" : "s"}`);
  for (const factor of spec.factors ?? []) {
    steps.push(
      factor.values && factor.values.length > 0
        ? `Vary ${factor.parameter} over ${factor.values.join(", ")}`
        : `Vary ${factor.parameter} in [${factor.lower ?? "?"}, ${factor.upper ?? "?"}]`,
    );
  }
  steps.push(`Observe ${(spec.outputs ?? []).join(", ") || "all outputs"}`);
  for (const analysis of spec.analyses ?? []) steps.push(`Analyze: ${analysis.method}`);

  return (
    <div className="si-plan" data-testid="si-plan">
      <p className="si-plan__lead">
        {proposal.rationale || `Here is a configuration for ${modelId} that addresses your question.`}
      </p>
      <dl className="si-plan__facts">
        <div>
          <dt>Model</dt>
          <dd>
            {modelId}
            {model ? ` · ${model.n_parameters} parameters, ${model.n_outputs} outputs` : ""}
          </dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{proposal.used_ai ? `AI provider (${proposal.provider})` : "Rule-based planner"}</dd>
        </div>
        <div>
          <dt>Validation</dt>
          <dd>{proposal.validation_ok ? "Passes the engine's checks" : "Needs correction"}</dd>
        </div>
      </dl>
      <p className="si-plan__heading">Proposed experiment</p>
      <ol className="si-plan__steps">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {proposal.assumptions.length > 0 ? (
        <>
          <p className="si-plan__heading">Assumptions</p>
          <ul className="si-plan__list">
            {proposal.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      <div className="si-plan__actions">
        <Button
          size="md"
          data-testid="si-review-in-manual"
          onClick={() => onReview(spec, modelId)}
        >
          Review in Manual
        </Button>
        <Button
          kind="tertiary"
          size="md"
          data-testid="si-run"
          disabled={running || !proposal.validation_ok}
          onClick={() => onRun(spec, modelId)}
        >
          Run
        </Button>
        <span className="si-plan__note">
          Nothing has run yet. Run validates with the engine first, then executes; Review in Manual
          exposes every setting before you commit.
        </span>
      </div>
    </div>
  );
}

/** SI page of one investigation (a stored experiment, or the unsaved draft). */
export function InvestigationSi({
  investigationId,
  onAttach,
  onSuggestionNav,
}: {
  investigationId: string;
  onAttach: () => void;
  onSuggestionNav: () => void;
}) {
  const ws = useWorkspace();
  const { messages, busy } = ws.conversation(investigationId);
  const [draft, setDraft] = useState("");
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const hasThread = messages.length > 0;
  const modelId = ws.schema?.model_id ?? ws.selectedModelId;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, busy]);

  function pick(item: Suggestion): void {
    if (item.prompt === null) {
      onSuggestionNav();
      return;
    }
    setDraft(item.prompt);
    areaRef.current?.focus();
  }

  const composer = (
    <Composer
      value={draft}
      onChange={setDraft}
      onSubmit={() => {
        void ws.ask(investigationId, draft.trim(), modelId);
        setDraft("");
      }}
      busy={busy}
      models={ws.models}
      selectedModelId={modelId}
      onSelectModel={ws.setSelectedModelId}
      placeholder="Ask SI about this investigation..."
      rows={hasThread ? 2 : 4}
      onAttach={onAttach}
      inputRef={areaRef}
    />
  );

  return (
    <div className={hasThread ? "si si--thread" : "si"} data-testid="si-view">
      {hasThread ? (
        <div className="si__scroll">
          <div className="si__column">
            {messages.map((message) =>
              message.role === "user" ? (
                <div key={message.id} className="si-msg si-msg--user">
                  {message.text}
                </div>
              ) : (
                <div key={message.id} className="si-msg si-msg--si">
                  <span className="si-msg__who">SI</span>
                  {message.kind === "plan" ? (
                    <PlanCard
                      message={message}
                      model={ws.models.find((m) => m.model_id === message.modelId)}
                      onReview={(spec, id) => void ws.reviewProposal(spec, id)}
                      onRun={(spec, id) => void ws.runProposal(spec, id)}
                      running={busy}
                    />
                  ) : (
                    <div className="si-plan" data-testid="si-error">
                      <p className="si-plan__lead">{message.text}</p>
                      {message.questions.length > 0 ? (
                        <ul className="si-plan__list">
                          {message.questions.map((q) => (
                            <li key={q}>{q}</li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  )}
                </div>
              ),
            )}
            {busy ? <p className="si-thinking">SI is preparing a proposal...</p> : null}
            <div ref={endRef} />
          </div>
        </div>
      ) : (
        <div className="si__welcome">
          <p className="drw-eyebrow" data-testid="si-name">
            SI &mdash; Scientific Intelligence
          </p>
          <h1 className="si__title">
            {investigationId === "draft" ? "What are you investigating?" : "How can I help with this investigation?"}
          </h1>
          <p className="si__sub">
            Turns a research question into a proposed, inspectable scientific workflow. Nothing runs
            without your approval.
          </p>
        </div>
      )}

      <div className="si__dock">
        <div className="si__column">
          {composer}
          {!hasThread ? <Suggestions items={INVESTIGATION_SUGGESTIONS} onPick={pick} /> : null}
          <p className="si__foot">
            {ws.plannerNote ? ws.plannerNote.note : "Checking planner configuration..."} Today SI
            proposes experiment configurations and hands them to Manual; analyses (sensitivity,
            identifiability, calibration) run from the Analysis page. SI proposes; you decide what
            runs.
          </p>
        </div>
      </div>
    </div>
  );
}
