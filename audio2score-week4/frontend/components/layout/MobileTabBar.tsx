"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FileMusic, Plus, User } from "lucide-react";

const TABS = [
  { href: "/create", label: "Create", icon: Plus },
  { href: "/dashboard", label: "My Scores", icon: FileMusic },
  { href: "/account", label: "Account", icon: User },
];

export default function MobileTabBar() {
  const pathname = usePathname();

  return (
    <nav className="ns-tabbar" aria-label="Mobile">
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const active =
          tab.href === "/create"
            ? pathname === "/create"
            : pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={"ns-tab" + (active ? " is-active" : "")}
            aria-current={active ? "page" : undefined}
          >
            <Icon size={20} aria-hidden="true" />
            <span>{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
