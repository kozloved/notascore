import type { ReactNode } from "react";

import Container from "../layout/Container";

export default function Section({
  id,
  kicker,
  title,
  children,
  width = "wide",
}: {
  id?: string;
  kicker?: string;
  title?: ReactNode;
  children: ReactNode;
  width?: "narrow" | "default" | "wide";
}) {
  return (
    <section className="ns-section" id={id}>
      <Container width={width}>
        {kicker ? <p className="ns-kicker">{kicker}</p> : null}
        {title ? <h2 className="ns-display ns-section-title">{title}</h2> : null}
        {children}
      </Container>
    </section>
  );
}
