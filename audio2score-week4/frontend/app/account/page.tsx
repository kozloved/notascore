"use client";

import { useRouter } from "next/navigation";

import AppShell from "../../components/layout/AppShell";
import RequireAuth from "../../components/auth/RequireAuth";
import { useAuth } from "../../components/auth/AuthProvider";
import ThemeToggle from "../../components/theme/ThemeToggle";
import Button from "../../components/ui/Button";
import ButtonLink from "../../components/ui/ButtonLink";
import { Display, Text } from "../../components/ui/Text";

export default function AccountPage() {
  return (
    <AppShell variant="app" width="narrow">
      <RequireAuth>
        <AccountBody />
      </RequireAuth>
    </AppShell>
  );
}

function AccountBody() {
  const { user, configured, signOut } = useAuth();
  const router = useRouter();

  if (!configured) {
    return (
      <>
        <Display as="h1">Account</Display>
        <Text className="tagline">
          Sign-in is not configured on this workspace yet. You can still create a
          score.
        </Text>
        <ThemeToggle />
        <div className="ns-page-cta">
          <ButtonLink href="/create">Create a score</ButtonLink>
        </div>
      </>
    );
  }

  return (
    <>
      <Display as="h1">Account</Display>
      <Text className="tagline">{user?.email}</Text>
      <div style={{ marginTop: 24 }}>
        <p className="ns-field-label">Theme</p>
        <ThemeToggle />
      </div>
      <div className="ns-page-cta">
        <ButtonLink href="/dashboard" variant="secondary">
          My Scores
        </ButtonLink>
        <Button
          variant="ghost"
          onClick={async () => {
            await signOut();
            router.push("/");
          }}
        >
          Log out
        </Button>
      </div>
    </>
  );
}
