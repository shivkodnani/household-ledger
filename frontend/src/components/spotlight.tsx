import * as React from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeftRight, ArrowUpRight, Clock3, FileText, Search, Store } from "lucide-react";
import { useLedger } from "@/lib/ledger";
import { money, shortDate } from "@/lib/utils";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandGroupLabel,
  CommandInput,
  CommandItem,
  CommandItemIcon,
  CommandList,
  CommandSeparator,
} from "@ui-sdk/react/command";
import {
  Dialog,
  DialogBackdrop,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@ui-sdk/react/dialog";

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

const commandItemClass = "flex min-h-12 cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm outline-none transition-colors data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground";

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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogBackdrop className="fixed inset-0 z-[90] bg-black/50 backdrop-blur-[2px] transition-opacity duration-150 data-[starting-style]:opacity-0 data-[ending-style]:opacity-0" />
      <DialogContent className="fixed left-1/2 top-[12vh] z-[100] w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 overflow-hidden rounded-xl border bg-popover p-0 text-popover-foreground shadow-2xl outline-none transition duration-200 data-[starting-style]:translate-y-2 data-[starting-style]:opacity-0 data-[ending-style]:translate-y-2 data-[ending-style]:opacity-0 sm:w-full">
        <DialogTitle className="sr-only">Spotlight search</DialogTitle>
        <DialogDescription className="sr-only">Search and open transactions, merchants, and statements.</DialogDescription>
        <Command query={query} onQueryChange={setQuery} filter={false} loop className="flex max-h-[min(72vh,620px)] w-full flex-col overflow-hidden">
          <div className="flex items-center gap-3 border-b px-4">
            <Search aria-hidden="true" className="size-5 shrink-0 text-muted-foreground" />
            <CommandInput
              autoFocus
              placeholder="Search transactions, merchants, statements…"
              aria-label="Search your household ledger"
              className="h-14 min-w-0 flex-1 border-0 bg-transparent text-base outline-none placeholder:text-muted-foreground focus-visible:ring-0"
            />
            <kbd className="hidden shrink-0 rounded border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline">ESC</kbd>
          </div>
          <CommandEmpty className="px-4 py-10 text-center text-sm text-muted-foreground">No matching records found.</CommandEmpty>
          <CommandList className="max-h-[min(60vh,480px)] overflow-y-auto p-2">
            {q ? (
              <>
                {transactionResults.length > 0 && (
                  <CommandGroup className="py-1">
                    <CommandGroupLabel className="px-3 py-2 text-xs font-medium text-muted-foreground">Transactions</CommandGroupLabel>
                    {transactionResults.map((item) => {
                      const searchable = [item.merchant, item.description, item.category, item.card_name, item.date].filter(Boolean).join(" ");
                      return (
                        <CommandItem
                          key={item.id}
                          value={`transaction:${item.id} ${searchable}`}
                          label={searchable}
                          onSelect={() => transactionPath(item.id, query)}
                          className={commandItemClass}
                        >
                          <CommandItemIcon className="grid size-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"><ArrowLeftRight aria-hidden="true" className="size-4" /></CommandItemIcon>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">{item.merchant || item.description}</span>
                            <span className="block truncate text-xs text-muted-foreground">{shortDate(item.date)} · {item.category} · {item.allocation}</span>
                          </span>
                          <span className="shrink-0 tabular text-xs text-muted-foreground">{money(item.amount_inr)}</span>
                          <ArrowUpRight aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                )}
                {merchantResults.length > 0 && (
                  <>
                    {transactionResults.length > 0 && <CommandSeparator className="my-1 h-px bg-border" />}
                    <CommandGroup className="py-1">
                      <CommandGroupLabel className="px-3 py-2 text-xs font-medium text-muted-foreground">Merchants</CommandGroupLabel>
                      {merchantResults.map((item) => {
                        const searchable = [item.display_name, item.legal_name, ...item.aliases].join(" ");
                        return (
                          <CommandItem key={item.id} value={`merchant:${item.id} ${searchable}`} label={searchable} onSelect={() => go("/merchants?search=" + encodeURIComponent(query) + "&focus=" + encodeURIComponent(item.id), query)} className={commandItemClass}>
                            <CommandItemIcon className="grid size-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"><Store aria-hidden="true" className="size-4" /></CommandItemIcon>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate font-medium">{item.display_name}</span>
                              <span className="block truncate text-xs text-muted-foreground">{item.legal_name || item.aliases.slice(0, 2).join(" · ") || "Merchant directory"}</span>
                            </span>
                            <ArrowUpRight aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  </>
                )}
                {statementResults.length > 0 && (
                  <>
                    {(transactionResults.length > 0 || merchantResults.length > 0) && <CommandSeparator className="my-1 h-px bg-border" />}
                    <CommandGroup className="py-1">
                      <CommandGroupLabel className="px-3 py-2 text-xs font-medium text-muted-foreground">Statements</CommandGroupLabel>
                      {statementResults.map((item) => {
                        const searchable = [item.filename, item.bank, item.card_name, item.period, item.statement_month].join(" ");
                        return (
                          <CommandItem key={item.id} value={`statement:${item.id} ${searchable}`} label={searchable} onSelect={() => go("/statements?search=" + encodeURIComponent(query) + "&focus=" + encodeURIComponent(item.id), query)} className={commandItemClass}>
                            <CommandItemIcon className="grid size-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"><FileText aria-hidden="true" className="size-4" /></CommandItemIcon>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate font-medium">{item.bank} · {item.card_name || item.period}</span>
                              <span className="block truncate text-xs text-muted-foreground">{item.filename}</span>
                            </span>
                            <ArrowUpRight aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  </>
                )}
              </>
            ) : (
              <>
                {prefs.recent.length > 0 && (
                  <CommandGroup className="py-1">
                    <CommandGroupLabel className="px-3 py-2 text-xs font-medium text-muted-foreground">Recent searches</CommandGroupLabel>
                    {prefs.recent.slice(0, 5).map((item, index) => (
                      <CommandItem key={`${item}:${index}`} value={`recent:${index} ${item}`} label={item} onSelect={() => setQuery(item)} className={commandItemClass}>
                        <CommandItemIcon className="text-muted-foreground"><Clock3 aria-hidden="true" className="size-4" /></CommandItemIcon>
                        <span className="min-w-0 flex-1 truncate">{item}</span>
                        <span className="text-xs text-muted-foreground">Search again</span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
                {frequent.length > 0 && (
                  <>
                    {prefs.recent.length > 0 && <CommandSeparator className="my-1 h-px bg-border" />}
                    <CommandGroup className="py-1">
                      <CommandGroupLabel className="px-3 py-2 text-xs font-medium text-muted-foreground">Frequently searched</CommandGroupLabel>
                      {frequent.map((item) => (
                        <CommandItem key={item.value} value={`frequent:${item.value}`} label={item.value} onSelect={() => setQuery(item.value)} className={commandItemClass}>
                          <CommandItemIcon className="text-muted-foreground"><Search aria-hidden="true" className="size-4" /></CommandItemIcon>
                          <span className="min-w-0 flex-1 truncate">{item.value}</span>
                          <span className="text-xs text-muted-foreground">{item.count} searches</span>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </>
                )}
                {prefs.recent.length === 0 && frequent.length === 0 && (
                  <CommandGroup className="py-1">
                    <CommandGroupLabel className="px-3 py-2 text-xs font-medium text-muted-foreground">Quick navigation</CommandGroupLabel>
                    {[
                      { label: "Review transactions", path: "/transactions", icon: ArrowLeftRight },
                      { label: "Open statements", path: "/statements", icon: FileText },
                      { label: "Merchant directory", path: "/merchants", icon: Store },
                    ].map((item) => {
                      const Icon = item.icon;
                      return (
                        <CommandItem key={item.path} value={`navigation:${item.path} ${item.label}`} label={item.label} onSelect={() => go(item.path)} className={commandItemClass}>
                          <CommandItemIcon className="text-muted-foreground"><Icon aria-hidden="true" className="size-4" /></CommandItemIcon>
                          <span>{item.label}</span>
                        </CommandItem>
                      );
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
        </Command>
      </DialogContent>
    </Dialog>
  );
}
