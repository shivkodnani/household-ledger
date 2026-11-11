import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { LedgerProvider, useLedger } from "@/lib/ledger";
import { Button } from "@/components/ui/button";
import { Toaster } from "sonner";
import { AppShell } from "@/components/app-shell";
import { LoginPage } from "@/pages/login";
const OverviewPage = lazy(() => import("@/pages/overview").then((module) => ({ default: module.OverviewPage })));
const TransactionsPage = lazy(() => import("@/pages/transactions").then((module) => ({ default: module.TransactionsPage })));
const StatementsPage = lazy(() => import("@/pages/statements").then((module) => ({ default: module.StatementsPage })));
const MerchantsPage = lazy(() => import("@/pages/merchants").then((module) => ({ default: module.MerchantsPage })));
const SettingsPage = lazy(() => import("@/pages/settings").then((module) => ({ default: module.SettingsPage })));

function PageLoading() {
  return <div className="grid min-h-64 place-items-center text-sm text-muted-foreground"><span className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin" /> Opening this section</span></div>;
}

function AppRoutes() {
  const { auth, loading, error, reload } = useLedger();
  const location = useLocation();
  if (loading && !auth) {
    return (
      <main className="grid min-h-svh place-items-center bg-background">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" /> Opening your household ledger
        </div>
      </main>
    );
  }
  if (error && !auth) {
    return (
      <main className="grid min-h-svh place-items-center bg-background p-6">
        <div className="max-w-sm space-y-4 text-center">
          <h1 className="text-lg font-semibold">Couldn’t connect to the ledger</h1>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button onClick={() => void reload()}><RefreshCw className="size-4" /> Try again</Button>
        </div>
      </main>
    );
  }
  if (!auth?.authenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname }} />} />
      </Routes>
    );
  }
  if (location.pathname === "/login") return <Navigate to="/" replace />;
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Suspense fallback={<PageLoading />}><OverviewPage /></Suspense>} />
        <Route path="transactions" element={<Suspense fallback={<PageLoading />}><TransactionsPage /></Suspense>} />
        <Route path="statements" element={<Suspense fallback={<PageLoading />}><StatementsPage /></Suspense>} />
        <Route path="merchants" element={<Suspense fallback={<PageLoading />}><MerchantsPage /></Suspense>} />
        <Route path="settings" element={<Suspense fallback={<PageLoading />}><SettingsPage /></Suspense>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <LedgerProvider>
      <AppRoutes />
      <Toaster position="bottom-right" richColors closeButton />
    </LedgerProvider>
  );
}
