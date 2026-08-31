"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import ThemeToggle from "../theme/ThemeToggle";
import AccountMenu from "./AccountMenu";
import Wordmark from "./Wordmark";

const LINKS = [
  { href: "/create", label: "Create" },
  { href: "/dashboard", label: "My Scores" },
];

export default function AppNavbar() {
  const pathname = usePathname();

  return (
    <header className="ns-nav ns-nav-app">
      <div className="ns-nav-inner">
        <Wordmark href="/create" />
        <nav className="ns-nav-links" aria-label="Application">
          {LINKS.map((link) => {
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
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
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
