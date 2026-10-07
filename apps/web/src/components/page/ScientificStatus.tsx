"use client";

import type { ReactNode } from "react";

/**
 * One consistent way to state the epistemic status of a result.
 *
 * DRW must never let a computation look like a scientific conclusion it is not.
 * Every analysis is tagged with exactly one level:
 *
 * - `descriptive`    a summary of behaviour; no predictive-validity claim
 * - `limited`        the current observations may not distinguish the parameters
 * - `not_validated`  fitted/derived, but not yet tested on independent observations
 * - `supported`      supported by the configured observations and evaluation
 *
 * The level is carried by a text tag, not by colour alone.
 */
export type ScientificLevel = "descriptive" | "limited" | "not_validated" | "supported";

const DEFAULT_TEXT: Record<ScientificLevel, string> = {
  descriptive:
    "This analysis describes how the model responds to parameter changes. It does not establish predictive validity.",
  limited: "Parameters may not be distinguishable with the current observations.",
  not_validated:
    "This model has been calibrated but has not yet been tested against independent observations.",
  supported: "This result is supported by the configured observations and evaluation.",
};

const LABEL: Record<ScientificLevel, string> = {
  descriptive: "Descriptive",
  limited: "Limited evidence",
  not_validated: "Not validated",
  supported: "Supported",
};

export function ScientificStatus({
  level,
  children,
  testId,
}: {
  level: ScientificLevel;
  children?: ReactNode;
  testId?: string;
}) {
  return (
    <div className="drw-epistemic" data-level={level} data-testid={testId} role="note">
      <span className="drw-epistemic__tag">{LABEL[level]}</span>
      <span className="drw-epistemic__text">{children ?? DEFAULT_TEXT[level]}</span>
    </div>
  );
}
