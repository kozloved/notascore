import type { ReactNode } from "react";
import Link from "next/link";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
type Size = "md" | "sm";

export default function ButtonLink({
  href,
  children,
  variant = "primary",
  size = "md",
  className = "",
  onClick,
}: {
  href: string;
  children: ReactNode;
  variant?: Variant;
  size?: Size;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <Link
      href={href}
      className={`ns-btn ns-btn-${variant} ns-btn-${size} ${className}`.trim()}
      onClick={onClick}
    >
      {children}
    </Link>
  );
}
