"use client";

import { useEffect, useState } from "react";

import { ArrowRight, MagicWandFilled } from "@carbon/icons-react";
import {
  Button,
  InlineNotification,
  Tag,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableRow,
  TextArea,
  UnorderedList,
  ListItem,
} from "@carbon/react";

import { Diagnostics } from "@/components/Diagnostics";
import { Section } from "@/components/Section";
import { ApiError, type DrwClient } from "@/lib/client";
import type { ExperimentSpec, PlanProposal, PlannerStatus } from "@/lib/types";

/**
 * Optional AI experiment planner.
 *
 * This panel **proposes** a spec. It never executes: the proposal must be
 * applied to the editor, then validated and approved through the normal
 * workflow. The deterministic rule-based planner is used when no LLM provider
 * is configured, so the workflow is fully usable without one.
 */
export function PlannerPanel({
  client,
  modelId,
  onApply,
}: {
  client: DrwClient;
  modelId: string;
  onApply: (spec: ExperimentSpec) => void;
}) {
  const [status, setStatus] = useState<PlannerStatus | null>(null);
  const [question, setQuestion] = useState("");
  const [context, setContext] = useState("");
  const [proposal, setProposal] = useState<PlanProposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorQuestions, setErrorQuestions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        setStatus(await client.plannerStatus());
      } catch {
        setStatus(null);
      }
    })();
  }, [client]);

  async function propose(): Promise<void> {
    setBusy(true);
    setError(null);
    setErrorQuestions([]);
    setProposal(null);
    try {
      setProposal(await client.planExperiment(modelId, question, context));
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
        const first = (caught.diagnostics as { questions?: string[] }[])[0];
        if (first && Array.isArray(first.questions)) setErrorQuestions(first.questions);
      } else {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      id="planner-heading"
      title="AI experiment planner (optional)"
      description={
        <span data-testid="planner-provider-note">
          {status ? status.note : "Checking planner configuration..."} Proposals are never executed
          automatically: applying one only fills the editor, and you still validate and press Run.
        </span>
      }
    >
      <div className="drw-stack-tight">
        <TextArea
          id="planner-question"
          labelText="Research question"
          placeholder="e.g. How does the prey peak change if alpha increases by 10%?"
          rows={2}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          data-testid="planner-question"
        />

        <TextArea
          id="planner-context"
          labelText="Additional context (optional)"
          placeholder="Known constraints, prior results, units..."
          rows={2}
          value={context}
          onChange={(event) => setContext(event.target.value)}
          data-testid="planner-context"
        />

        <div>
          <Button
            renderIcon={MagicWandFilled}
            onClick={() => void propose()}
            disabled={busy || question.trim().length === 0}
            data-testid="planner-propose"
          >
            {busy ? "Proposing..." : "Propose experiment"}
          </Button>
        </div>

        {error ? (
          <div data-testid="planner-error">
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title="Planner"
              subtitle={error}
            />
          </div>
        ) : null}
        {errorQuestions.length > 0 ? (
          <UnorderedList>
            {errorQuestions.map((item) => (
              <ListItem key={item}>{item}</ListItem>
            ))}
          </UnorderedList>
        ) : null}

        {proposal ? <Proposal proposal={proposal} onApply={onApply} /> : null}
      </div>
    </Section>
  );
}

function Proposal({
  proposal,
  onApply,
}: {
  proposal: PlanProposal;
  onApply: (spec: ExperimentSpec) => void;
}) {
  if (proposal.questions.length > 0 || proposal.spec === null) {
    return (
      <div className="drw-stack-tight" data-testid="planner-questions">
        <h3 className="drw-subheading">More information needed</h3>
        <UnorderedList>
          {proposal.questions.map((item) => (
            <ListItem key={item}>{item}</ListItem>
          ))}
        </UnorderedList>
      </div>
    );
  }

  const spec = proposal.spec;
  const interventions = (spec.factors ?? []).map((factor) => {
    if (factor.values && factor.values.length > 0) {
      return `${factor.parameter} = ${factor.values.join(", ")}`;
    }
    return `${factor.parameter} in [${factor.lower ?? "?"}, ${factor.upper ?? "?"}] steps ${
      factor.steps ?? "?"
    }`;
  });
  const baseline = Object.entries(spec.baseline ?? {})
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");

  return (
    <div className="drw-stack-tight drw-proposal" data-testid="planner-proposal">
      <h3 className="drw-subheading">Proposal</h3>
      <p className="drw-muted" data-testid="planner-source">
        Source: {proposal.used_ai ? `AI provider (${proposal.provider})` : "rule-based planner"} ·{" "}
        {proposal.rationale}
      </p>

      <div className="drw-row drw-row--center">
        <span data-testid="planner-validation">
          <Tag type={proposal.validation_ok ? "green" : "red"}>
            {proposal.validation_ok ? "passes validation" : "needs correction"}
          </Tag>
        </span>
        <span className="drw-muted">Applied as a proposal only; nothing has run.</span>
      </div>

      <h4 className="drw-subheading">User input</h4>
      <p className="drw-muted">“{spec.hypothesis}”</p>

      <TableContainer title="Baseline and intervention">
        <Table aria-label="Proposed experiment summary" size="md">
          <TableBody>
            <TableRow>
              <TableCell>baseline</TableCell>
              <TableCell className="drw-mono">{baseline}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>interventions</TableCell>
              <TableCell className="drw-mono">
                {interventions.length > 0 ? interventions.join("; ") : "none"}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell>outputs</TableCell>
              <TableCell className="drw-mono">
                {(spec.outputs ?? []).join(", ") || "all"}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell>analyses</TableCell>
              <TableCell className="drw-mono">
                {(spec.analyses ?? []).map((a) => a.method).join(", ") || "delta"}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
      <p className="drw-hint">
        The estimated run count comes from the engine when you validate.
      </p>

      <h4 className="drw-subheading">Assumptions and open questions</h4>
      <UnorderedList data-testid="planner-assumptions">
        {proposal.assumptions.map((item) => (
          <ListItem key={item}>{item}</ListItem>
        ))}
      </UnorderedList>

      {proposal.diagnostics.length > 0 ? (
        <Diagnostics diagnostics={proposal.diagnostics} />
      ) : null}

      <div>
        <Button renderIcon={ArrowRight} onClick={() => onApply(spec)} data-testid="planner-apply">
          Apply proposal to editor
        </Button>
      </div>
      <p className="drw-hint">
        Applying fills the editor only. Validate, review and press Run to execute - an AI proposal is
        never executed automatically.
      </p>
    </div>
  );
}
