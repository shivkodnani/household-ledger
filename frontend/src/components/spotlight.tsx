import * as React from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeftRight, ArrowUpRight, Clock3, FileText, Search, Store } from "lucide-react";
import { useLedger } from "@/lib/ledger";
import { money, shortDate } from "@/lib/utils";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

type SearchPrefs = { recent: string[]; frequent: Record<string, number> };

function readPrefs(): SearchPrefs {
  try {
    const value = JSON.parse(localStorage.getItem("household-ledger-search-history") || "{}");
    return { recent: Array.isArray(value.recent) ? value.recent : [], frequent: value.frequent || {} };
  } catch {
    return { recent: [], frequent: {} };
  }
}

function rememberQuery(query: string) {
  const normalized = query.trim();
  if (!normalized) return;
  const prefs = readPrefs();
  const key = normalized.toLocaleLowerCase();
  prefs.recent = [normalized, ...prefs.recent.filter((item) => item.toLocaleLowerCase() !== key)].slice(0, 8);
  prefs.frequent[key] = (prefs.frequent[key] || 0) + 1;
  try { localStorage.setItem("household-ledger-search-history", JSON.stringify(prefs)); } catch {}
}

export function Spotlight({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  const { transactions, merchants, statements } = useLedger();
  const navigate = useNavigate();
  const [query, setQuery] = React.useState("");
  const [prefs, setPrefs] = React.useState<SearchPrefs>(readPrefs);

  React.useEffect(() => {
    if (open) {
      setQuery("");
      setPrefs(readPrefs());
    }
  }, [open]);

  function finish(searchQuery: string) {
    rememberQuery(searchQuery);
    setPrefs(readPrefs());
  }

  function go(path: string, searchQuery?: string) {
    if (searchQuery) finish(searchQuery);
    onOpenChange(false);
    navigate(path);
  }

  function transactionPath(id: string, searchQuery: string) {
    const params = new URLSearchParams();
    params.set("search", searchQuery);
    params.set("focus", id);
    params.set("include", "all");
    go("/transactions?" + params.toString(), searchQuery);
  }

  const q = query.trim().toLocaleLowerCase();
  const transactionResults = q
    ? transactions.filter((item) => [item.merchant, item.description, item.category, item.card_name].some((value) => value?.toLocaleLowerCase().includes(q))).slice(0, 5)
    : [];
  const merchantResults = q
    ? merchants.filter((item) => [item.display_name, item.legal_name, ...item.aliases].some((value) => value?.toLocaleLowerCase().includes(q))).slice(0, 3)
    : [];
  const statementResults = q
    ? statements.filter((item) => [item.filename, item.bank, item.card_name, item.period, item.statement_month].some((value) => value?.toLocaleLowerCase().includes(q))).slice(0, 3)
    : [];
  const frequent = Object.entries(prefs.frequent)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([value, count]) => ({ value, count }));

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} label="Spotlight search">
      <CommandInput
        autoFocus
        placeholder="Search transactions, merchants, statements…"
        value={query}
        onValueChange={setQuery}
        aria-label="Search your household ledger"
      />
      <CommandList>
        <CommandEmpty>No matching records found.</CommandEmpty>
        {q ? (
          <>
            {transactionResults.length > 0 && (
              <CommandGroup heading="Transactions">
                {transactionResults.map((item) => (
                  <CommandItem
                    key={item.id}
                    value={[item.merchant, item.description, item.category, item.card_name, item.date].filter(Boolean).join(" ")}
                    onSelect={() => transactionPath(item.id, query)}
                    className="gap-3"
                  >
                    <span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted"><ArrowLeftRight className="size-4" /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{item.merchant || item.description}</span>
                      <span className="block truncate text-xs text-muted-foreground">{shortDate(item.date)} · {item.category} · {item.allocation}</span>
                    </span>
                    <span className="tabular text-xs text-muted-foreground">{money(item.amount_inr)}</span>
                    <ArrowUpRight className="size-3.5 text-muted-foreground" />
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {merchantResults.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Merchants">
                  {merchantResults.map((item) => (
                  <CommandItem key={item.id} value={[item.display_name, item.legal_name, ...item.aliases].join(" ")} onSelect={() => go("/merchants?search=" + encodeURIComponent(query) + "&focus=" + encodeURIComponent(item.id), query)} className="gap-3">
                      <span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted"><Store className="size-4" /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{item.display_name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{item.legal_name || item.aliases.slice(0, 2).join(" · ") || "Merchant directory"}</span>
                      </span>
                      <ArrowUpRight className="size-3.5 text-muted-foreground" />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {statementResults.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Statements">
                  {statementResults.map((item) => (
                  <CommandItem key={item.id} value={[item.filename, item.bank, item.card_name, item.period, item.statement_month].join(" ")} onSelect={() => go("/statements?search=" + encodeURIComponent(query) + "&focus=" + encodeURIComponent(item.id), query)} className="gap-3">
                      <span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted"><FileText className="size-4" /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{item.bank} · {item.card_name || item.period}</span>
                        <span className="block truncate text-xs text-muted-foreground">{item.filename}</span>
                      </span>
                      <ArrowUpRight className="size-3.5 text-muted-foreground" />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </>
        ) : (
          <>
            {prefs.recent.length > 0 && (
              <CommandGroup heading="Recent searches">
                {prefs.recent.slice(0, 5).map((item) => (
                  <CommandItem key={item} value={"recent " + item} onSelect={() => setQuery(item)} className="gap-3">
                    <Clock3 className="size-4 text-muted-foreground" />
                    <span className="flex-1">{item}</span>
                    <span className="text-xs text-muted-foreground">Search again</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {frequent.length > 0 && (
              <>
                {prefs.recent.length > 0 && <CommandSeparator />}
                <CommandGroup heading="Frequently searched">
                  {frequent.map((item) => (
                    <CommandItem key={item.value} value={"frequent " + item.value} onSelect={() => setQuery(item.value)} className="gap-3">
                      <Search className="size-4 text-muted-foreground" />
                      <span className="flex-1">{item.value}</span>
                      <span className="text-xs text-muted-foreground">{item.count} searches</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {prefs.recent.length === 0 && frequent.length === 0 && (
              <CommandGroup heading="Quick navigation">
                {[
                  { label: "Review transactions", path: "/transactions", icon: ArrowLeftRight },
                  { label: "Open statements", path: "/statements", icon: FileText },
                  { label: "Merchant directory", path: "/merchants", icon: Store },
                ].map((item) => {
                  const Icon = item.icon;
                  return <CommandItem key={item.path} value={item.label} onSelect={() => go(item.path)} className="gap-3"><Icon className="size-4" />{item.label}</CommandItem>;
                })}
              </CommandGroup>
            )}
          </>
        )}
      </CommandList>
      <div className="flex items-center justify-between border-t px-4 py-2.5 text-[11px] text-muted-foreground">
        <span>Use ↑ ↓ to move and ↵ to open</span>
        <span>Press <kbd className="ml-1 rounded border bg-muted px-1.5 py-0.5">⌘ K</kbd> to search</span>
      </div>
    </CommandDialog>
  );
}
