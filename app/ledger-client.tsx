"use client";

import dynamic from "next/dynamic";

const LedgerEntry = dynamic(
  () => import("@/next-entry").then((module) => module.NextEntry),
  {
    ssr: false,
    loading: () => (
      <main className="grid min-h-svh place-items-center bg-background text-sm text-muted-foreground">
        Opening your household ledger
      </main>
    ),
  },
);

export function LedgerClient() {
  return <LedgerEntry />;
}
