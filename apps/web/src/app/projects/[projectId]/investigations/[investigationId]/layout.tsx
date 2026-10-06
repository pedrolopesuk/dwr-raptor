import type { ReactNode } from "react";

import { InvestigationFrame } from "@/components/shell/InvestigationFrame";

export default function Layout({ children }: { children: ReactNode }) {
  return <InvestigationFrame>{children}</InvestigationFrame>;
}
