import * as React from "react";
import { Link } from "react-router-dom";
import { ArrowDownLeft, ArrowUpRight, Banknote, CalendarDays, ChevronDown, CircleAlert, CreditCard, Plus, ReceiptText, Wallet } from "lucide-react";
import type { Transaction } from "@/lib/types";
import { money, monthLabel } from "@/lib/utils";
import { useLedger } from "@/lib/ledger";
import { PageHeading } from "@/components/page-heading";
import { TransactionsTable } from "@/components/transactions-table";
import { TransactionDialog } from "@/components/transaction-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";

function amountOf(items: Transaction[]) {
  return items.reduce((total, item) => total + Number(item.amount_inr || 0), 0);
}

function Metric({
  label,
  value,
  detail,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "warning" | "muted";
}) {
  return (
    <Card className="transition-shadow duration-200 hover:shadow-md">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <span className={"grid size-9 place-items-center rounded-lg " + (tone === "warning" ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300" : "bg-muted text-foreground")}>
            <Icon className="size-4" />
          </span>
        </div>
        <p className="mt-4 text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

export function OverviewPage() {
  const { transactions, statements, merchants } = useLedger();
  const [months, setMonths] = React.useState<string[]>([]);
  const monthsInitialized = React.useRef(false);
  const [monthMenuOpen, setMonthMenuOpen] = React.useState(false);
  const [bank, setBank] = React.useState("all");
  const [card, setCard] = React.useState("all");
  const [transactionOpen, setTransactionOpen] = React.useState(false);
  const availableMonths = React.useMemo(
    () => [...new Set([
      ...statements.map((item) => item.statement_month).filter(Boolean),
      ...transactions.map((item) => item.statement_month || item.date?.slice(0, 7)).filter(Boolean),
    ] as string[])].sort().reverse(),
    [statements, transactions],
  );
  const years = [...new Set(availableMonths.map((month) => month.slice(0, 4)))];

  React.useEffect(() => {
    if (!monthsInitialized.current && availableMonths.length) {
      const latestStatementMonth = statements.map((item) => item.statement_month).filter(Boolean).sort().reverse()[0];
      setMonths([latestStatementMonth || availableMonths[0]]);
      monthsInitialized.current = true;
    }
  }, [availableMonths, statements]);

  const selectedMonths = months.filter((month) => availableMonths.includes(month));
  const monthText = selectedMonths.length === 1 ? monthLabel(selectedMonths[0]) : selectedMonths.length ? selectedMonths.length + " months" : "Select months";
  const monthTransactions = transactions.filter((item) => selectedMonths.includes(item.statement_month || item.date?.slice(0, 7) || ""));
  const banks = [...new Set(monthTransactions.map((item) => item.bank).filter(Boolean) as string[])].sort();
  const cards = [...new Set(monthTransactions.filter((item) => bank === "all" || item.bank === bank).map((item) => item.card_name).filter(Boolean) as string[])].sort();
  const scoped = monthTransactions.filter((item) => (bank === "all" || item.bank === bank) && (card === "all" || item.card_name === card));
  const owed = scoped.reduce((sum, item) => sum + Number(item.owed_inr || 0), 0);
  const pending = scoped.filter((item) => item.allocation === "Needs review" || item.ocr_amount_match === 0);
  const reviewed = scoped.filter((item) => item.allocation !== "Needs review");
  const purchases = scoped.filter((item) => item.kind === "Purchase");
  const refunds = scoped.filter((item) => item.kind === "Refund");
  const categories = Object.entries(
    purchases.reduce<Record<string, number>>((totals, item) => {
      totals[item.category || "Uncategorised"] = (totals[item.category || "Uncategorised"] || 0) + Number(item.amount_inr || 0);
      return totals;
    }, {}),
  ).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const maxCategory = Math.max(1, ...categories.map((item) => item[1]));
  const reconciliation = statements.filter(
    (item) => selectedMonths.includes(item.statement_month || "") &&
      (bank === "all" || item.bank === bank) &&
      (card === "all" || item.card_name === card) &&
      item.reconciliation_status === "needs attention",
  );

  function toggleMonth(month: string, checked: boolean | "indeterminate") {
    setMonths((current) => checked ? [...new Set([...current, month])].sort().reverse() : current.filter((item) => item !== month));
    setBank("all");
    setCard("all");
  }

  return (
    <>
      <PageHeading
        title="Overview"
        description="A statement-month view of your household spending and balance."
        actions={
          <>
            <Button variant="outline" asChild><Link to="/statements"><ReceiptText />Statements</Link></Button>
            <Button variant="outline" onClick={() => setTransactionOpen(true)}><Plus />Add transaction</Button>
          </>
        }
      />

      <div className="mb-5 flex flex-col gap-3 rounded-xl border bg-card p-3 sm:flex-row sm:items-end sm:p-4">
        <div className="w-full space-y-1.5 sm:w-64">
          <p className="text-xs font-medium text-muted-foreground">Statement months</p>
          <Popover open={monthMenuOpen} onOpenChange={setMonthMenuOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" className="w-full justify-between font-normal">
                <span className="flex items-center gap-2 truncate"><CalendarDays className="size-4 text-muted-foreground" />{monthText}</span>
                <ChevronDown className="size-4 text-muted-foreground" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-72 p-0">
              <div className="max-h-80 overflow-y-auto p-3">
                {years.length ? years.map((year) => (
                  <section key={year} className="mb-3 last:mb-0">
                    <p className="mb-2 text-xs font-semibold text-muted-foreground">{year}</p>
                    <div className="grid gap-1">
                      {availableMonths.filter((month) => month.startsWith(year)).map((month) => (
                        <label key={month} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-accent">
                          <Checkbox checked={selectedMonths.includes(month)} onCheckedChange={(checked) => toggleMonth(month, checked)} />
                          <span>{monthLabel(month).split(" ")[0]}</span>
                        </label>
                      ))}
                    </div>
                  </section>
                )) : <p className="p-3 text-sm text-muted-foreground">Upload a statement to start your monthly view.</p>}
              </div>
              <Separator />
              <div className="flex items-center justify-between p-2.5">
                <span className="text-xs text-muted-foreground">{selectedMonths.length} selected</span>
                <Button variant="ghost" size="sm" onClick={() => { setMonths([]); setBank("all"); setCard("all"); }}>Clear</Button>
              </div>
            </PopoverContent>
          </Popover>
        </div>
        <div className="grid w-full grid-cols-2 gap-3 sm:w-auto">
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Bank</p>
            <Select value={bank} onValueChange={(value) => { setBank(value); setCard("all"); }}>
              <SelectTrigger className="min-w-36"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">All banks</SelectItem>{banks.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Card</p>
            <Select value={card} onValueChange={setCard}>
              <SelectTrigger className="min-w-36"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">All cards</SelectItem>{cards.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </div>
        <p className="ml-auto pb-2 text-xs text-muted-foreground">{selectedMonths.length ? selectedMonths.length + " selected · " + scoped.length + " structured lines" : "Choose a statement month"}</p>
      </div>

      {reconciliation.map((statement) => (
        <Alert key={statement.id} variant="warning" className="mb-4">
          <CircleAlert className="size-4" />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <AlertTitle>{statement.bank} · {statement.statement_month || statement.period} needs reconciliation</AlertTitle>
              <AlertDescription>
                Extracted charges: {money(statement.extracted_charges_inr)} · Statement charges: {money(statement.expected_charges_inr)} · Difference: {money(Math.abs(Number(statement.reconciliation_difference_inr || 0)))}
              </AlertDescription>
            </div>
            <Button variant="outline" size="sm" asChild><Link to={"/transactions?statement=" + encodeURIComponent(statement.id) + "&include=all"}>Review statement lines</Link></Button>
          </div>
        </Alert>
      ))}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Wife owes you" value={money(owed)} detail="Based on saved allocations in selected months" icon={Wallet} />
        <Metric label="Needs review" value={String(pending.length)} detail={pending.length ? "Transactions waiting for your decision" : "You’re all caught up"} icon={CircleAlert} tone={pending.length ? "warning" : "muted"} />
        <Metric label="Purchase volume" value={money(amountOf(purchases))} detail={purchases.length + " purchase line items recorded"} icon={CreditCard} />
        <Metric label="Refunds" value={money(refunds.reduce((sum, item) => sum + Math.abs(Number(item.amount_inr || 0)), 0))} detail={refunds.length + " refund line items"} icon={ArrowDownLeft} />
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(280px,.85fr)]">
        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
            <div>
              <CardTitle className="text-base">Recent transactions</CardTitle>
              <CardDescription className="mt-1">Structured activity for the selected statement months</CardDescription>
            </div>
            <Button variant="ghost" size="sm" asChild><Link to="/transactions">View all <ArrowUpRight /></Link></Button>
          </CardHeader>
          <CardContent className="p-0">
            <TransactionsTable items={scoped.slice(0, 6)} showActions={false} emptyTitle="No transactions in this selection" emptyText="Choose another month or add a statement." />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Balance breakdown</CardTitle>
            <CardDescription>{reviewed.length} allocated line items · INR basis</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <p className="text-xs text-muted-foreground">Amount owed in selected months</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{money(owed)}</p>
            </div>
            <Separator />
            {categories.length ? (
              <div className="space-y-4">
                {categories.map(([category, amount]) => (
                  <div key={category}>
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                      <span className="truncate text-muted-foreground">{category}</span>
                      <span className="shrink-0 font-medium tabular-nums">{money(amount)}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-primary/75 transition-[width] duration-500" style={{ width: Math.max(3, amount / maxCategory * 100) + "%" }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted-foreground">Category totals appear as purchase lines are reviewed.</div>
            )}
            <div className="rounded-lg bg-muted/60 p-3 text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium text-foreground">Analytics source</span><br />
              Totals come from structured transaction history. PDFs are retained as source documents.
            </div>
          </CardContent>
        </Card>
      </section>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3 text-sm">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Banknote className="size-4" />
          <span>{transactions.length} structured transactions · {merchants.length} merchants in your directory</span>
        </div>
        <Button variant="ghost" size="sm" asChild><Link to="/merchants">Manage merchants <ArrowUpRight /></Link></Button>
      </div>

      <TransactionDialog open={transactionOpen} onOpenChange={setTransactionOpen} />
    </>
  );
}
