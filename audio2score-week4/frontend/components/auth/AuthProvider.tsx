"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Session, User } from "@supabase/supabase-js";

import { isSupabaseConfigured, supabase } from "../../lib/supabase";
import { authErrorMessage } from "../../lib/auth-errors";
import { rememberNextPath, safeNextPath } from "../../lib/redirect";
import { attachAccountScores } from "../../lib/jobs";

type AuthContextValue = {
  user: User | null;
  session: Session | null;
  loading: boolean;
  configured: boolean;
  signInWithGoogle: (next?: string) => Promise<string | null>;
  signInWithEmail: (email: string, password: string) => Promise<string | null>;
  signUpWithEmail: (
    email: string,
    password: string
  ) => Promise<{ error: string | null; needsVerification: boolean }>;
  resetPassword: (email: string) => Promise<string | null>;
  resendVerification: (email: string) => Promise<string | null>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const attached = useRef(false);

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setLoading(false);
      return;
    }

    let mounted = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      setSession(data.session ?? null);
      setLoading(false);
    });

    const { data: subscription } = supabase.auth.onAuthStateChange(
      (_event, next) => {
        setSession(next);
        setLoading(false);
      }
    );

    return () => {
      mounted = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!session?.access_token) {
      attached.current = false;
      return;
    }
    if (attached.current) return;
    attached.current = true;
    void attachAccountScores();
  }, [session?.access_token]);

  const signInWithGoogle = useCallback(async (next?: string) => {
    if (!isSupabaseConfigured) {
      return "Sign-in is not available on this workspace yet.";
    }
    rememberNextPath(safeNextPath(next));
    const redirectTo = `${window.location.origin}/login`;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo },
    });
    return error ? authErrorMessage(error) : null;
  }, []);

  const signInWithEmail = useCallback(async (email: string, password: string) => {
    if (!isSupabaseConfigured) {
      return "Sign-in is not available on this workspace yet.";
    }
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    return error ? authErrorMessage(error) : null;
  }, []);

  const signUpWithEmail = useCallback(async (email: string, password: string) => {
    if (!isSupabaseConfigured) {
      return {
        error: "Sign-in is not available on this workspace yet.",
        needsVerification: false,
      };
    }
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/create` },
    });
    if (error) {
      return { error: authErrorMessage(error), needsVerification: false };
    }
    return {
      error: null,
      needsVerification: !data.session,
    };
  }, []);

  const resetPassword = useCallback(async (email: string) => {
    if (!isSupabaseConfigured) {
      return "Sign-in is not available on this workspace yet.";
    }
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/login`,
    });
    return error ? "We couldn’t send a reset email. Check the address and try again." : null;
  }, []);

  const resendVerification = useCallback(async (email: string) => {
    if (!isSupabaseConfigured) {
      return "Sign-in is not available on this workspace yet.";
    }
    const { error } = await supabase.auth.resend({ type: "signup", email });
    return error ? "We couldn’t send another email. Please try again." : null;
  }, []);

  const signOut = useCallback(async () => {
    if (!isSupabaseConfigured) return;
    await supabase.auth.signOut();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      session,
      loading,
      configured: isSupabaseConfigured,
      signInWithGoogle,
      signInWithEmail,
      signUpWithEmail,
      resetPassword,
      resendVerification,
      signOut,
    }),
    [
      session,
      loading,
      signInWithGoogle,
      signInWithEmail,
      signUpWithEmail,
      resetPassword,
      resendVerification,
      signOut,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
