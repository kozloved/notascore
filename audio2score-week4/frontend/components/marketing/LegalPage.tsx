import type { ReactNode } from "react";

import AppShell from "../../components/layout/AppShell";
import { Display, Text } from "../../components/ui/Text";

export default function LegalLayout({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <AppShell variant="public" width="default">
      <p className="ns-kicker">NotaScore</p>
      <Display as="h1">{title}</Display>
      <Text className="tagline">{description}</Text>
      <div className="ns-legal">{children}</div>
    </AppShell>
  );
}
