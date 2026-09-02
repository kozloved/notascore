"use client";

import { useState } from "react";
import Link from "next/link";

import AppShell from "../../components/layout/AppShell";
import { useAuth } from "../../components/auth/AuthProvider";
import Alert from "../../components/ui/Alert";
import Button from "../../components/ui/Button";
import Input from "../../components/ui/Input";
import { Display, Text } from "../../components/ui/Text";

export default function ForgotPasswordPage() {
  const { resetPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    const message = await resetPassword(email);
    setBusy(false);
    if (message) {
      setError(message);
      return;
    }
    setSent(true);
  };

  return (
    <AppShell variant="public" width="narrow">
      <Display as="h1">Reset your password</Display>
      {sent ? (
        <>
          <Text className="tagline" size="body-large">
            Check your email
          </Text>
          <Text>
            We’ve sent you a link to reset your password.
          </Text>
        </>
      ) : (
        <>
          <Text className="tagline">
            Enter the email on your account. We’ll send a reset link if it exists.
          </Text>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <form className="ns-auth-form" onSubmit={onSubmit}>
            <Input
              label="Email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Button type="submit" loading={busy}>
              Send reset email
            </Button>
          </form>
        </>
      )}
      <p className="ns-auth-links">
        <Link href="/login">Back to log in</Link>
      </p>
    </AppShell>
  );
}
