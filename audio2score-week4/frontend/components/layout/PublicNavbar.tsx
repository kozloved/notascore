"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";

import ThemeToggle from "../theme/ThemeToggle";
import IconButton from "../ui/IconButton";
import Wordmark from "./Wordmark";

const LINKS = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#create", label: "Examples" },
];

export default function PublicNavbar() {
  const [open, setOpen] = useState(false);

  return (
    <header className="ns-nav">
      <div className="ns-nav-inner">
        <Wordmark />
        <nav className="ns-nav-links" aria-label="Primary">
          {LINKS.map((link) => (
            <Link key={link.href} href={link.href} className="ns-nav-link">
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="ns-nav-actions">
          <ThemeToggle compact />
          <Link href="/login" className="ns-nav-link ns-nav-login">
            Log in
          </Link>
          <Link href="/#create" className="ns-btn ns-btn-primary ns-nav-cta">
            Create a score
          </Link>
        </div>
        <IconButton
          className="ns-nav-menu-btn"
          label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </IconButton>
      </div>
      {open ? (
        <div className="ns-nav-drawer" id="mobile-nav">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="ns-nav-drawer-link"
              onClick={() => setOpen(false)}
            >
              {link.label}
            </Link>
          ))}
          <Link href="/login" className="ns-nav-drawer-link" onClick={() => setOpen(false)}>
            Log in
          </Link>
          <Link
            href="/#create"
            className="ns-btn ns-btn-primary"
            onClick={() => setOpen(false)}
          >
            Create a score
          </Link>
          <ThemeToggle />
        </div>
      ) : null}
    </header>
  );
}
