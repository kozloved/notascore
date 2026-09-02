"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "./AuthProvider";

export default function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, configured } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!configured || loading || user) return;
    const next = encodeURIComponent(pathname || "/create");
    router.replace(`/login?next=${next}`);
  }, [configured, loading, user, pathname, router]);

  if (!configured) return <>{children}</>;
  if (loading) {
    return <p className="ns-text ns-tone-muted">Loading your account…</p>;
  }
  if (!user) return <p className="ns-text ns-tone-muted">Redirecting to log in…</p>;
  return <>{children}</>;
}
