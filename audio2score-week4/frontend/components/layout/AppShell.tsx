import type { ReactNode } from "react";

import AppNavbar from "./AppNavbar";
import Container from "./Container";
import MobileTabBar from "./MobileTabBar";
import PublicNavbar from "./PublicNavbar";

type AppShellProps = {
  children: ReactNode;
  variant?: "public" | "app";
  width?: "narrow" | "default" | "wide";
};

export default function AppShell({
  children,
  variant = "app",
  width = "default",
}: AppShellProps) {
  return (
    <div className={"ns-shell" + (variant === "app" ? " has-tabbar" : "")}>
      {variant === "public" ? <PublicNavbar /> : <AppNavbar />}
      <main id="main" className="ns-main">
        <Container width={width}>{children}</Container>
      </main>
      {variant === "app" ? <MobileTabBar /> : null}
    </div>
  );
}
