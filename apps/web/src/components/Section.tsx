"use client";

import type { ReactNode } from "react";

import { Layer } from "@carbon/react";

/**
 * Standard page section: a Carbon surface with a heading block. Content inside
 * sits one layer up (`Layer`) so Carbon form fields and tables pick the correct
 * field/background tokens on both light and dark themes.
 */
export function Section({
  id,
  title,
  description,
  actions,
  children,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="drw-card" aria-labelledby={id}>
      <header className="drw-card__header drw-card__bar">
        <div>
          <h2 id={id} className="drw-card__title">
            {title}
          </h2>
          {description ? <p className="drw-card__desc">{description}</p> : null}
        </div>
        {actions}
      </header>
      <Layer>{children}</Layer>
    </section>
  );
}
