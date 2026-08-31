"use client";

import type { ReactNode } from "react";

import { ThemeProvider } from "./theme/ThemeProvider";

export function Providers({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}
