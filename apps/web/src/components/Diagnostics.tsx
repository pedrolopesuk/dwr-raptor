"use client";

import { InlineNotification } from "@carbon/react";

import type { Diagnostic } from "@/lib/types";

const KIND = {
  error: "error",
  warning: "warning",
  info: "info",
} as const;

export function Diagnostics({ diagnostics }: { diagnostics: Diagnostic[] }) {
  if (diagnostics.length === 0) {
    return <p className="drw-muted">No diagnostics.</p>;
  }
  return (
    <div className="drw-stack-tight" aria-label="Diagnostics">
      {diagnostics.map((diagnostic, index) => (
        <InlineNotification
          key={`${diagnostic.code}-${index}`}
          kind={KIND[diagnostic.level]}
          lowContrast
          hideCloseButton
          title={diagnostic.code}
          subtitle={diagnostic.message}
        />
      ))}
    </div>
  );
}
