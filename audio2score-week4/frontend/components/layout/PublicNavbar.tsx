"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";

import { PUBLIC_NAV } from "../../lib/site";
import { track } from "../../lib/analytics";
import { useAuth } from "../auth/AuthProvider";
import ThemeToggle from "../theme/ThemeToggle";
import IconButton from "../ui/IconButton";
import Wordmark from "./Wordmark";

export default function PublicNavbar() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const { user } = useAuth();

  return (
    <header className="ns-nav">
      <div className="ns-nav-inner">
        <Wordmark href="/" />
        <nav className="ns-nav-links" aria-label="Primary">
          {PUBLIC_NAV.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={
                "ns-nav-link" + (pathname === link.href ? " is-active" : "")
              }
              aria-current={pathname === link.href ? "page" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="ns-nav-actions">
          <ThemeToggle compact />
          {user ? (
            <Link href="/dashboard" className="ns-nav-link ns-nav-login">
              My Scores
            </Link>
          ) : (
            <Link href="/login" className="ns-nav-link ns-nav-login">
              Log in
            </Link>
          )}
          <Link
            href="/create"
            className="ns-btn ns-btn-primary ns-nav-cta"
            onClick={() => track("hero_create_clicked")}
          >
            Create a score
          </Link>
        </div>
        <div className="ns-nav-menu-wrap">
          <IconButton
            className="ns-nav-menu-btn"
            label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X size={20} /> : <Menu size={20} />}
          </IconButton>
        </div>
      </div>
      {open ? (
        <div className="ns-nav-drawer" id="mobile-nav">
          {PUBLIC_NAV.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="ns-nav-drawer-link"
              onClick={() => setOpen(false)}
            >
              {link.label}
            </Link>
          ))}
          {user ? (
            <Link
              href="/dashboard"
              className="ns-nav-drawer-link"
              onClick={() => setOpen(false)}
            >
              My Scores
            </Link>
          ) : (
            <Link
              href="/login"
              className="ns-nav-drawer-link"
              onClick={() => setOpen(false)}
            >
              Log in
            </Link>
          )}
          <Link
            href="/create"
            className="ns-btn ns-btn-primary"
            onClick={() => {
              setOpen(false);
              track("hero_create_clicked");
            }}
          >
            Create a score
          </Link>
          <ThemeToggle />
        </div>
      ) : null}
    </header>
  );
}
