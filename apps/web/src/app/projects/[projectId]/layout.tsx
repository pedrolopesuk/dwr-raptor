import type { ReactNode } from "react";

import { ProjectShell } from "@/components/shell/ProjectShell";

export default function Layout({ children }: { children: ReactNode }) {
  return <ProjectShell>{children}</ProjectShell>;
}
