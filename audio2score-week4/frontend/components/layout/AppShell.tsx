import type { ReactNode } from "react";

import AppNavbar from "./AppNavbar";
import Container from "./Container";
import MobileTabBar from "./MobileTabBar";
import PublicFooter from "./PublicFooter";
import PublicNavbar from "./PublicNavbar";

type AppShellProps = {
  children: ReactNode;
  variant?: "public" | "app";
  width?: "narrow" | "default" | "wide";
  contained?: boolean;
};

export default function AppShell({
  children,
  variant = "app",
  width = "default",
  contained = true,
}: AppShellProps) {
  return (
    <div
      className={
        "ns-shell" +
        (variant === "app" ? " has-tabbar" : "") +
        (contained ? "" : " is-flush")
      }
    >
      {variant === "public" ? <PublicNavbar /> : <AppNavbar />}
      <main id="main" className="ns-main">
        {contained ? <Container width={width}>{children}</Container> : children}
      </main>
      {variant === "public" ? <PublicFooter /> : null}
      {variant === "app" ? <MobileTabBar /> : null}
    </div>
  );
}
