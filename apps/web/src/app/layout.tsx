import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.scss";

export const metadata: Metadata = {
  title: "DRW - Differential Research Workbench",
  description:
    "Define an experiment, run a scientific model, compare outcomes and export reproducible evidence.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
