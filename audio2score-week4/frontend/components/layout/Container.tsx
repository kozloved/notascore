import type { HTMLAttributes, ReactNode } from "react";

export default function Container({
  children,
  className = "",
  width = "default",
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  width?: "narrow" | "default" | "wide";
}) {
  return (
    <div className={`ns-container ns-container-${width} ${className}`.trim()} {...props}>
      {children}
    </div>
  );
}
