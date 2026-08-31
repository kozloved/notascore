"use client";

import type { ReactNode } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

import type { ThemePreference } from "../../lib/theme";
import { useTheme } from "./ThemeProvider";
import SegmentedControl from "../ui/SegmentedControl";

const OPTIONS: {
  value: ThemePreference;
  label: string;
  icon: ReactNode;
}[] = [
  { value: "system", label: "System", icon: <Monitor aria-hidden="true" size={15} strokeWidth={1.75} /> },
  { value: "light", label: "Light", icon: <Sun aria-hidden="true" size={15} strokeWidth={1.75} /> },
  { value: "dark", label: "Dark", icon: <Moon aria-hidden="true" size={15} strokeWidth={1.75} /> },
];

export default function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { preference, setPreference } = useTheme();

  return (
    <SegmentedControl
      label="Theme"
      value={preference}
      onChange={setPreference}
      options={OPTIONS}
      compact={compact}
    />
  );
}
