import * as React from "react";
import { toast } from "sonner";
import type {
  AuthState,
  BackupStatus,
  Merchant,
  MerchantDiscovery,
  Statement,
  Transaction,
  User,
} from "./types";
import { shareForAllocation } from "./utils";

type LedgerContextValue = {
  auth: AuthState | null;
  transactions: Transaction[];
  merchants: Merchant[];
  statements: Statement[];
  discoveries: MerchantDiscovery[];
  discoveryMeta: { counts: Record<string, number>; search_available: boolean };
  adminUsers: User[];
  backupMeta: BackupStatus;
  loading: boolean;
  error: string;
  api: <T = any>(path: string, options?: RequestInit) => Promise<T>;
  reload: () => Promise<void>;
  applyAllocation: (ids: string[], allocation: string, sharePercent?: number) => Promise<void>;
  setTransactions: React.Dispatch<React.SetStateAction<Transaction[]>>;
  loadDiscoveries: () => Promise<void>;
  loadPasskeys: () => Promise<Passkey[]>;
};

export type Passkey = {
  id: string;
  nickname: string;
  device_type: string;
  backed_up: number;
  created_at: string;
  last_used_at?: string | null;
  transports: string[];
};

const LedgerContext = React.createContext<LedgerContextValue | null>(null);

export function LedgerProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = React.useState<AuthState | null>(null);
  const [transactions, setTransactions] = React.useState<Transaction[]>([]);
  const [merchants, setMerchants] = React.useState<Merchant[]>([]);
  const [statements, setStatements] = React.useState<Statement[]>([]);
  const [discoveries, setDiscoveries] = React.useState<MerchantDiscovery[]>([]);
  const [discoveryMeta, setDiscoveryMeta] = React.useState({ counts: {} as Record<string, number>, search_available: false });
  const [adminUsers, setAdminUsers] = React.useState<User[]>([]);
  const [backupMeta, setBackupMeta] = React.useState<BackupStatus>({ configured: false, backups: [] });
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const csrfRef = React.useRef("");
  const authRequiredRef = React.useRef(false);

  const api = React.useCallback(async <T,>(path: string, options: RequestInit = {}) => {
    const method = (options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers);
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (authRequiredRef.current && ["POST", "PUT", "PATCH", "DELETE"].includes(method) && csrfRef.current) {
      headers.set("X-CSRF-Token", csrfRef.current);
    }
    const response = await fetch(path, { ...options, headers, cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      window.location.assign("/login");
      throw new Error("Your session ended. Sign in again.");
    }
    if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data as T;
  }, []);

  const loadDiscoveries = React.useCallback(async () => {
    const data = await api<{
      items: MerchantDiscovery[];
      counts: Record<string, number>;
      search_available: boolean;
    }>("/api/merchant-discoveries");
    setDiscoveries(data.items);
    setDiscoveryMeta({ counts: data.counts || {}, search_available: data.search_available });
  }, [api]);

  const reload = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const state = await api<AuthState>("/api/auth/status");
      csrfRef.current = state.csrf_token || "";
      authRequiredRef.current = state.auth_required;
      if (!state.authenticated) {
        setAuth(state);
        setTransactions([]);
        setMerchants([]);
        setStatements([]);
        setDiscoveries([]);
        setAdminUsers([]);
        setBackupMeta({ configured: false, backups: [] });
        return;
      }
      const isAdmin = state.user?.role === "admin";
      const [tx, merchantRows, statementRows, discoveriesData, users, backups] = await Promise.all([
        api<{ items: Transaction[] }>("/api/transactions"),
        api<Merchant[]>("/api/merchants"),
        api<Statement[]>("/api/statements"),
        api<{ items: MerchantDiscovery[]; counts: Record<string, number>; search_available: boolean }>("/api/merchant-discoveries"),
        isAdmin && state.auth_required ? api<User[]>("/api/admin/users") : Promise.resolve([] as User[]),
        isAdmin ? api<BackupStatus>("/api/admin/backups") : Promise.resolve({ configured: false, backups: [] } as BackupStatus),
      ]);
      setTransactions(tx.items);
      setMerchants(merchantRows);
      setStatements(statementRows);
      setDiscoveries(discoveriesData.items);
      setDiscoveryMeta({ counts: discoveriesData.counts || {}, search_available: discoveriesData.search_available });
      setAdminUsers(users);
      setBackupMeta(backups);
      setAuth(state);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your ledger.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const applyAllocation = React.useCallback(
    async (ids: string[], allocation: string, sharePercent = 0) => {
      if (!ids.length) return;
      const previous = transactions;
      const percent = allocation === "Custom" ? sharePercent : shareForAllocation(allocation);
      setTransactions((current) =>
        current.map((item) =>
          ids.includes(item.id)
            ? { ...item, allocation, share_percent: percent, owed_inr: Number(item.amount_inr) * percent / 100 }
            : item,
        ),
      );
      try {
        await api("/api/transactions/bulk", {
          method: "POST",
          body: JSON.stringify({
            items: ids.map((id) => ({ id, allocation, share_percent: percent })),
          }),
        });
      } catch (err) {
        setTransactions(previous);
        toast.error(err instanceof Error ? err.message : "Could not save allocation.");
        return;
      }
    },
    [api, transactions],
  );

  const loadPasskeys = React.useCallback(() => api<Passkey[]>("/api/auth/passkeys"), [api]);

  const value = React.useMemo(
    () => ({
      auth,
      transactions,
      merchants,
      statements,
      discoveries,
      discoveryMeta,
      adminUsers,
      backupMeta,
      loading,
      error,
      api,
      reload,
      applyAllocation,
      setTransactions,
      loadDiscoveries,
      loadPasskeys,
    }),
    [
      auth,
      transactions,
      merchants,
      statements,
      discoveries,
      discoveryMeta,
      adminUsers,
      backupMeta,
      loading,
      error,
      api,
      reload,
      applyAllocation,
      loadDiscoveries,
      loadPasskeys,
    ],
  );
  return <LedgerContext.Provider value={value}>{children}</LedgerContext.Provider>;
}

export function useLedger() {
  const value = React.useContext(LedgerContext);
  if (!value) throw new Error("useLedger must be used inside LedgerProvider.");
  return value;
}
