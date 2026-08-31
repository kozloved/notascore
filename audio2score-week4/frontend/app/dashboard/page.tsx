"use client";

import AppShell from "../../components/layout/AppShell";
import RequireAuth from "../../components/auth/RequireAuth";
import ButtonLink from "../../components/ui/ButtonLink";
import { Display, Text } from "../../components/ui/Text";

export default function DashboardPage() {
  return (
    <AppShell variant="app" width="default">
      <RequireAuth>
        <Display as="h1">My Scores</Display>
        <Text className="tagline">
          Scores you create will live here once accounts are connected to jobs.
          Create a score now — you can export immediately.
        </Text>
        <div className="ns-page-cta">
          <ButtonLink href="/create">Create a score</ButtonLink>
        </div>
      </RequireAuth>
    </AppShell>
  );
}
