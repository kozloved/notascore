"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import ThemeToggle from "../theme/ThemeToggle";
import Wordmark from "./Wordmark";

const LINKS = [
  { href: "/", label: "Create" },
  { href: "/dashboard", label: "My Scores" },
];

export default function AppNavbar() {
  const pathname = usePathname();

  return (
    <header className="ns-nav ns-nav-app">
      <div className="ns-nav-inner">
        <Wordmark />
        <nav className="ns-nav-links" aria-label="Application">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={"ns-nav-link" + (active ? " is-active" : "")}
                aria-current={active ? "page" : undefined}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <div className="ns-nav-actions">
          <ThemeToggle compact />
          <Link href="/login" className="ns-nav-link ns-nav-login">
            Account
          </Link>
        </div>
      </div>
    </header>
  );
}
