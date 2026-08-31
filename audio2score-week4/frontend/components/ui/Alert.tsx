import type { ReactNode } from "react";

type AlertTone = "success" | "error" | "info";

export default function Alert({
  tone = "info",
  children,
}: {
  tone?: AlertTone;
  children: ReactNode;
}) {
  return (
    <div className={`ns-alert ns-alert-${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
