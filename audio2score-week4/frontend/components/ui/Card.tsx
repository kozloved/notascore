import type { HTMLAttributes, ReactNode } from "react";

type CardProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  padded?: boolean;
};

export default function Card({
  children,
  className = "",
  padded = true,
  ...props
}: CardProps) {
  return (
    <div
      className={`ns-card ${padded ? "ns-card-padded" : ""} ${className}`.trim()}
      {...props}
    >
      {children}
    </div>
  );
}
