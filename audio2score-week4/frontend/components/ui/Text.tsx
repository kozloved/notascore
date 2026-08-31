import type { HTMLAttributes, ReactNode } from "react";

type TextProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  as?: "p" | "span" | "div";
  tone?: "primary" | "secondary" | "muted";
  size?: "body" | "body-large" | "body-small" | "caption" | "label" | "metadata";
};

export function Text({
  as: Tag = "p",
  tone = "secondary",
  size = "body",
  className = "",
  children,
  ...props
}: TextProps) {
  return (
    <Tag className={`ns-text ns-text-${size} ns-tone-${tone} ${className}`.trim()} {...props}>
      {children}
    </Tag>
  );
}

export function Display({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <p className={`ns-display ${className}`.trim()}>{children}</p>;
}

export function Heading({
  as: Tag = "h2",
  children,
  className = "",
}: {
  as?: "h1" | "h2" | "h3";
  children: ReactNode;
  className?: string;
}) {
  return <Tag className={`ns-heading ns-heading-${Tag} ${className}`.trim()}>{children}</Tag>;
}
