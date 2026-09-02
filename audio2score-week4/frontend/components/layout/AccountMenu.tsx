"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "../auth/AuthProvider";

function initials(email?: string, name?: string) {
  const source = (name || email || "N").trim();
  return source.slice(0, 1).toUpperCase();
}

export default function AccountMenu() {
  const { user, loading, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (loading) {
    return <span className="ns-avatar is-pending" aria-hidden="true" />;
  }

  if (!user) {
    return (
      <Link href="/login" className="ns-nav-link ns-nav-login">
        Account
      </Link>
    );
  }

  const name =
    (typeof user.user_metadata?.full_name === "string" &&
      user.user_metadata.full_name) ||
    user.email ||
    "Account";

  return (
    <div className="ns-menu" ref={wrapRef}>
      <button
        type="button"
        className="ns-avatar"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen((v) => !v)}
      >
        {initials(user.email, name)}
      </button>
      {open ? (
        <div className="ns-menu-panel" role="menu">
          <p className="ns-menu-email">{user.email}</p>
          <Link href="/account" role="menuitem" onClick={() => setOpen(false)}>
            Account
          </Link>
          <Link href="/dashboard" role="menuitem" onClick={() => setOpen(false)}>
            My Scores
          </Link>
          <Link href="/pricing" role="menuitem" onClick={() => setOpen(false)}>
            Subscription
          </Link>
          <Link href="/account" role="menuitem" onClick={() => setOpen(false)}>
            Settings
          </Link>
          <Link href="/help" role="menuitem" onClick={() => setOpen(false)}>
            Help
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setOpen(false);
              await signOut();
              router.push("/");
            }}
          >
            Log out
          </button>
        </div>
      ) : null}
    </div>
  );
}
