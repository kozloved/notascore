import { Suspense } from "react";

import AppShell from "../../components/layout/AppShell";
import AuthForm from "../../components/auth/AuthForm";

export const metadata = {
  title: "Create an account",
  description: "Create a NotaScore account to save your scores.",
};

export default function SignupPage() {
  return (
    <AppShell variant="public" width="narrow">
      <Suspense fallback={<p className="ns-tone-muted">Loading…</p>}>
        <AuthForm mode="signup" />
      </Suspense>
    </AppShell>
  );
}
