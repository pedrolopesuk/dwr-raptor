"use client";

import type { ReactNode } from "react";

import { NavLink } from "@/components/shell/NavLink";

/** One page = one cognitive job. Title, one-line purpose, optional actions. */
export function Page({
  title,
  purpose,
  actions,
  children,
  testId,
}: {
  title: string;
  purpose?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="drw-page drw-stack" data-testid={testId}>
      <header className="drw-page-header drw-page-header--row">
        <div>
          <h1 className="drw-page-title">{title}</h1>
          {purpose ? <p className="drw-page-subtitle">{purpose}</p> : null}
        </div>
        {actions ? <div className="drw-page-actions">{actions}</div> : null}
      </header>
      {children}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
  testId,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <div className="drw-empty" data-testid={testId}>
      <p className="drw-empty__title">{title}</p>
      {children ? <div className="drw-empty__body">{children}</div> : null}
      {action ? <div className="drw-empty__action">{action}</div> : null}
    </div>
  );
}

export type StateKind = "done" | "pending" | "failed" | "warning" | "unavailable" | "running";

const STATE_GLYPH: Record<StateKind, string> = {
  done: "✓",
  pending: "○",
  failed: "✕",
  warning: "⚠",
  unavailable: "–",
  running: "●",
};

const STATE_WORD: Record<StateKind, string> = {
  done: "done",
  pending: "not done",
  failed: "failed",
  warning: "warning",
  unavailable: "unavailable",
  running: "running",
};

/** Glyph plus a text word, so state is never carried by colour alone. */
export function StateMark({ kind }: { kind: StateKind }) {
  return (
    <span className="drw-state" data-state={kind}>
      <span aria-hidden="true">{STATE_GLYPH[kind]}</span>
      <span className="drw-sr">{STATE_WORD[kind]}</span>
    </span>
  );
}

/** Secondary navigation inside one investigation section. */
export function SubNav({
  label,
  items,
}: {
  label: string;
  items: { href: string; label: string; current: boolean }[];
}) {
  return (
    <nav className="drw-subnav" aria-label={label}>
      {items.map((item) => (
        <NavLink key={item.href} href={item.href} current={item.current} className="drw-subnav__item">
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
