"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ArrowUp, Attachment } from "@carbon/icons-react";
import { Button, Select, SelectItem, Tag, TextArea } from "@carbon/react";

import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import type {
  ModelSummary,
  SIActionPreview,
  SIActionRef,
  SIAnalysis,
  SIInterpretation,
  SIPlan,
  SIPlanStep,
} from "@/lib/types";

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

/** SI's structured reading of the current state (known / missing / unsupported). */
function AnalysisBlock({ analysis }: { analysis: SIAnalysis }) {
  const lists: { heading: string; items: string[]; tone?: "warn" }[] = [
    { heading: "Known", items: analysis.known },
    { heading: "Missing information", items: analysis.missing_information, tone: "warn" },
    { heading: "Not currently supported", items: analysis.unsupported_requests, tone: "warn" },
    { heading: "Caveats", items: analysis.caveats },
  ];
  return (
    <div className="si-analysis" data-testid="si-analysis">
      <p className="si-plan__lead">{analysis.understanding}</p>
      {analysis.state_summary.length > 0 ? (
        <ul className="si-plan__list si-plan__list--muted">
          {analysis.state_summary.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {lists
        .filter((list) => list.items.length > 0)
        .map((list) => (
          <div key={list.heading}>
            <p className="si-plan__heading" data-tone={list.tone}>
              {list.heading}
            </p>
            <ul className="si-plan__list">
              {list.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
    </div>
  );
}

function actionLabel(actionId: string, actions: SIActionRef[]): SIActionRef | undefined {
  return actions.find((action) => action.action_id === actionId);
}

function stepStatusTag(step: SIPlanStep): {
  type: "green" | "blue" | "red" | "magenta" | "gray" | "cool-gray";
  text: string;
} {
  if (step.status === "executed") return { type: "green", text: "Executed" };
  if (step.status === "failed") return { type: "red", text: "Failed" };
  if (step.status === "unsupported") return { type: "magenta", text: "Unsupported" };
  if (step.status === "rejected") return { type: "gray", text: "Rejected" };
  if (step.status === "approved") return { type: "blue", text: "Approved" };
  return { type: "cool-gray", text: "Proposed" };
}

function StepCard({
  step,
  action,
  busy,
  selected,
  runnable,
  onPreview,
  onExecute,
  onReject,
}: {
  step: SIPlanStep;
  action: SIActionRef | undefined;
  busy: boolean;
  selected: boolean;
  runnable: boolean;
  onPreview: () => void;
  onExecute: () => void;
  onReject: () => void;
}) {
  const pending = step.status === "proposed" || step.status === "approved";
  const mutating = action ? !action.read_only : true;
  const tag = stepStatusTag(step);
  return (
    <li className="si-step" data-testid={`si-step-${step.step_id}`} data-status={step.status}>
      <div className="si-step__head">
        <span className="si-step__action drw-mono">{step.action_id}</span>
        <Tag type={tag.type} size="sm">
          {tag.text}
        </Tag>
        {mutating ? (
          <Tag type="outline" size="sm">
            Requires approval
          </Tag>
        ) : (
          <Tag type="outline" size="sm">
            Read-only
          </Tag>
        )}
      </div>
      <p className="si-step__purpose">{step.purpose}</p>
      {action ? <p className="si-step__name">{action.name}</p> : null}
      {step.scientific_rationale ? (
        <p className="si-step__rationale">Why: {step.scientific_rationale}</p>
      ) : null}
      {step.execution ? (
        <p className="si-step__result" data-ok={step.execution.ok}>
          {step.execution.summary}
          {step.execution.error_message ? ` — ${step.execution.error_message}` : ""}
        </p>
      ) : null}
      {pending ? (
        <div className="si-step__actions">
          <Button
            kind="ghost"
            size="sm"
            onClick={onPreview}
            data-testid={`si-review-${step.step_id}`}
            aria-pressed={selected}
          >
            Review
          </Button>
          <Button
            size="sm"
            disabled={busy || !runnable}
            onClick={onExecute}
            data-testid={`si-run-${step.step_id}`}
            title={runnable ? undefined : "Run the earlier steps this one depends on first"}
          >
            {mutating ? "Approve & run" : "Run"}
          </Button>
          <Button
            kind="danger--ghost"
            size="sm"
            disabled={busy}
            onClick={onReject}
            data-testid={`si-reject-${step.step_id}`}
          >
            Reject
          </Button>
        </div>
      ) : null}
    </li>
  );
}

function PreviewPanel({ preview }: { preview: SIActionPreview }) {
  const errors = preview.input_diagnostics.filter((item) => item.level === "error");
  return (
    <div className="si-preview" data-testid="si-preview">
      <p className="si-plan__heading">What will run</p>
      <p className="si-plan__lead">{preview.summary}</p>
      <dl className="si-plan__facts">
        <div>
          <dt>Action</dt>
          <dd className="drw-mono">{preview.action_id}</dd>
        </div>
        <div>
          <dt>Effects</dt>
          <dd>{preview.effects.replace(/_/g, " ")}</dd>
        </div>
        <div>
          <dt>Approval</dt>
          <dd>{preview.requires_approval ? "Required" : "Not required (read-only)"}</dd>
        </div>
      </dl>
      {Object.keys(preview.inputs).length > 0 ? (
        <pre className="drw-pre" tabIndex={0} data-testid="si-preview-inputs">
          {JSON.stringify(preview.inputs, null, 2)}
        </pre>
      ) : (
        <p className="si-plan__note">This step takes no inputs.</p>
      )}
      {errors.map((item) => (
        <p key={`${item.code}-${item.message}`} className="drw-error-text">
          {item.code}: {item.message}
        </p>
      ))}
      {preview.warnings.map((item) => (
        <p key={item} className="si-plan__note">
          {item}
        </p>
      ))}
    </div>
  );
}

function InterpretationPanel({ interpretation }: { interpretation: SIInterpretation }) {
  const groups: { heading: string; items: string[] }[] = [
    { heading: "What this establishes", items: interpretation.establishes },
    { heading: "What it does not establish", items: interpretation.does_not_establish },
    { heading: "Limitations", items: interpretation.limitations },
    { heading: "Proposed next steps", items: interpretation.next_steps },
  ];
  return (
    <div className="si-interpretation" data-testid="si-interpretation">
      <p className="si-plan__heading">Interpretation</p>
      <p className="si-plan__lead">{interpretation.text}</p>
      {groups
        .filter((group) => group.items.length > 0)
        .map((group) => (
          <div key={group.heading}>
            <p className="si-plan__heading">{group.heading}</p>
            <ul className="si-plan__list">
              {group.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      {Object.keys(interpretation.artifacts).length > 0 ? (
        <p className="si-plan__note drw-mono">
          {Object.entries(interpretation.artifacts)
            .map(([key, value]) => `${key}=${value}`)
            .join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

function PlanPanel({
  plan,
  actionById,
  busy,
  selectedStepId,
  onPreview,
  onExecute,
  onReject,
}: {
  plan: SIPlan;
  actionById: Map<string, SIActionRef>;
  busy: boolean;
  selectedStepId: string | null;
  onPreview: (stepId: string) => void;
  onExecute: (stepId: string) => void;
  onReject: (stepId: string) => void;
}) {
  const executedIds = new Set(
    plan.steps.filter((step) => step.status === "executed").map((step) => step.step_id),
  );
  return (
    <div className="si-plan" data-testid="si-plan">
      <p className="si-plan__lead">
        {plan.rationale || "Here is the plan SI proposes for this investigation."}
      </p>
      <dl className="si-plan__facts">
        <div>
          <dt>Plan</dt>
          <dd className="drw-mono">{plan.plan_id}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{plan.used_ai ? "AI provider" : "Rule-based planner"}</dd>
        </div>
        <div>
          <dt>Steps</dt>
          <dd>{plan.steps.length}</dd>
        </div>
      </dl>
      {plan.open_questions.length > 0 ? (
        <div data-testid="si-plan-questions">
          <p className="si-plan__heading">Open questions</p>
          <ul className="si-plan__list">
            {plan.open_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="si-plan__heading">Proposed steps</p>
      <ol className="si-plan__steps">
        {plan.steps.map((step) => {
          const draft = step.status === "proposed" || step.status === "approved";
          const runnable =
            draft && step.depends_on.every((id) => executedIds.has(id));
          return (
            <StepCard
              key={step.step_id}
              step={step}
              action={actionById.get(step.action_id)}
              busy={busy}
              selected={selectedStepId === step.step_id}
              runnable={runnable}
              onPreview={() => onPreview(step.step_id)}
              onExecute={() => onExecute(step.step_id)}
              onReject={() => onReject(step.step_id)}
            />
          );
        })}
      </ol>
      <p className="si-plan__note">
        Nothing runs without approval. Read-only steps inspect state; every step that creates or
        changes an artifact shows exactly what it will do and waits for your decision. Steps run in
        order.
      </p>
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
  const [draft, setDraft] = useState("");
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const modelId = ws.schema?.model_id ?? ws.selectedModelId;
  const siState = ws.siState?.investigation_id === investigationId ? ws.siState : null;
  const messages = siState?.messages ?? [];
  const hasThread = messages.length > 0;
  const actionById = useMemo(
    () => new Map(ws.siActions.map((action) => [action.action_id, action])),
    [ws.siActions],
  );
  const plan = useMemo(
    () => siState?.plans.find((item) => item.plan_id === siState.current_plan_id) ?? null,
    [siState],
  );

  useEffect(() => {
    void ws.loadSi(investigationId, modelId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investigationId, modelId]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, ws.siBusy, plan?.steps.length]);

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
        void ws.askSi(investigationId, draft.trim(), modelId);
        setDraft("");
      }}
      busy={ws.siBusy}
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
      {hasThread || plan ? (
        <div className="si__scroll">
          <div className="si__column">
            {messages.map((message) =>
              message.role === "user" ? (
                <div key={message.message_id} className="si-msg si-msg--user">
                  {message.text}
                </div>
              ) : (
                <div key={message.message_id} className="si-msg si-msg--si">
                  <span className="si-msg__who">SI</span>
                  {message.analysis ? (
                    <AnalysisBlock analysis={message.analysis} />
                  ) : (
                    <p className="si-plan__lead">{message.text}</p>
                  )}
                </div>
              ),
            )}

            {plan ? (
              <PlanPanel
                plan={plan}
                actionById={actionById}
                busy={ws.siBusy}
                selectedStepId={ws.siPreviewStepId}
                onPreview={(stepId) => void ws.previewSiStep(investigationId, stepId, modelId)}
                onExecute={(stepId) => void ws.executeSiStep(investigationId, stepId, modelId)}
                onReject={(stepId) => void ws.rejectSiStep(investigationId, stepId)}
              />
            ) : null}

            {ws.siPreview ? <PreviewPanel preview={ws.siPreview} /> : null}
            {ws.siLastInterpretation ? (
              <InterpretationPanel interpretation={ws.siLastInterpretation} />
            ) : null}
            {ws.siBusy ? <p className="si-thinking">SI is working...</p> : null}
            <div ref={endRef} />
          </div>
        </div>
      ) : (
        <div className="si__welcome">
          <p className="drw-eyebrow" data-testid="si-name">
            SI &mdash; Scientific Intelligence
          </p>
          <h1 className="si__title">
            {investigationId === "draft"
              ? "What are you investigating?"
              : "How can I help with this investigation?"}
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
          {ws.siError ? (
            <p className="drw-error-text" data-testid="si-error" role="alert">
              {ws.siError}
            </p>
          ) : null}
          {!hasThread ? <Suggestions items={INVESTIGATION_SUGGESTIONS} onPick={pick} /> : null}
          <p className="si__foot">
            {ws.siProvider ? ws.siProvider.note : "Checking SI configuration..."} SI proposes and
            interprets; DRW computes and records. {ws.siActions.length} controlled action(s) are
            available.
          </p>
        </div>
      </div>
    </div>
  );
}
