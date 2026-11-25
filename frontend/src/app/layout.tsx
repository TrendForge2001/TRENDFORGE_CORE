import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { WorkspaceProvider } from "@/components/workspace-state";
import "./workspace.css";

export const metadata: Metadata = {
  title: "TrendForge Workbench",
  description: "Market scanner and backtesting workspace",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <WorkspaceProvider>{children}</WorkspaceProvider>
      </body>
    </html>
  );
}
