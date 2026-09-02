"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import AppShell from "../../components/layout/AppShell";
import { useAuth } from "../../components/auth/AuthProvider";
import Alert from "../../components/ui/Alert";
import Button from "../../components/ui/Button";
import { Display, Text } from "../../components/ui/Text";

function VerifyInner() {
  const params = useSearchParams();
  const email = params.get("email") || "";
  const { resendVerification } = useAuth();
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const resend = async () => {
    if (!email) return;
    setBusy(true);
    setError("");
    const message = await resendVerification(email);
    setBusy(false);
    if (message) {
      setError(message);
      return;
    }
    setStatus("We’ve sent another email.");
  };

  return (
    <>
      <Display as="h1">Check your email</Display>
      <Text className="tagline" size="body-large">
        We’ve sent a verification link
        {email ? ` to ${email}` : " to your email address"}.
      </Text>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {status ? <Alert tone="success">{status}</Alert> : null}
      <div className="ns-auth-form">
        <Button onClick={resend} loading={busy} disabled={!email}>
          Resend email
        </Button>
        <Link href="/signup" className="ns-text-link">
          Change email
        </Link>
      </div>
    </>
  );
}

export default function VerifyEmailPage() {
  return (
    <AppShell variant="public" width="narrow">
      <Suspense fallback={<p className="ns-tone-muted">Loading…</p>}>
        <VerifyInner />
      </Suspense>
    </AppShell>
  );
}
