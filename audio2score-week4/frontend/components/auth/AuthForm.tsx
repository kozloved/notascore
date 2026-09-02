"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { track, type AnalyticsEvent } from "../../lib/analytics";
import { consumeNextPath, rememberNextPath, safeNextPath } from "../../lib/redirect";
import { useAuth } from "./AuthProvider";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import Input from "../ui/Input";
import { Display, Text } from "../ui/Text";

type Mode = "login" | "signup";

export default function AuthForm({ mode }: { mode: Mode }) {
  const { user, loading, signInWithGoogle, signInWithEmail, signUpWithEmail } =
    useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"google" | "email" | null>(null);

  useEffect(() => {
    if (params.get("next")) rememberNextPath(next);
  }, [params, next]);

  useEffect(() => {
    const event: AnalyticsEvent = mode === "login" ? "login_started" : "signup_started";
    track(event);
  }, [mode]);

  useEffect(() => {
    if (loading || !user) return;
    const dest = params.get("next") ? next : consumeNextPath();
    router.replace(dest);
  }, [loading, user, next, params, router]);

  const onGoogle = async () => {
    setError("");
    setBusy("google");
    const message = await signInWithGoogle(next);
    if (message) {
      setError(message);
      setBusy(null);
    }
  };

  const onEmail = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy("email");
    if (mode === "login") {
      const message = await signInWithEmail(email, password);
      setBusy(null);
      if (message) setError(message);
      return;
    }
    const result = await signUpWithEmail(email, password);
    setBusy(null);
    if (result.error) {
      setError(result.error);
      return;
    }
    track("signup_completed");
    if (result.needsVerification) {
      router.push(`/verify-email?email=${encodeURIComponent(email)}`);
      return;
    }
    router.replace(next);
  };

  return (
    <div className="ns-auth">
      <Display as="h1">
        {mode === "login" ? "Welcome back" : "Create your NotaScore account"}
      </Display>
      <Text className="tagline">
        {mode === "login"
          ? "Continue to your scores, or start a new one from a recording."
          : "Save your scores and continue transcribing your music."}
      </Text>

      {error ? <Alert tone="error">{error}</Alert> : null}

      <Button
        variant="primary"
        onClick={onGoogle}
        loading={busy === "google"}
        disabled={busy !== null}
      >
        Continue with Google
      </Button>

      <p className="ns-auth-or">or</p>

      <form className="ns-auth-form" onSubmit={onEmail}>
        <Input
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          label="Password"
          name="password"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" loading={busy === "email"} disabled={busy !== null}>
          {mode === "login" ? "Log in" : "Create account"}
        </Button>
      </form>

      {mode === "login" ? (
        <p className="ns-auth-links">
          <Link href="/forgot-password">Forgot password?</Link>
          <span>
            Don’t have an account? <Link href={`/signup?next=${encodeURIComponent(next)}`}>Create one</Link>
          </span>
        </p>
      ) : (
        <p className="ns-auth-links">
          <span>
            Already have an account?{" "}
            <Link href={`/login?next=${encodeURIComponent(next)}`}>Log in</Link>
          </span>
        </p>
      )}
    </div>
  );
}
