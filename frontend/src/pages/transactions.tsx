import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Eye, FileText, LoaderCircle, PencilLine, Plus, RotateCcw, Search, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { useLedger } from "@/lib/ledger";
import type { Transaction } from "@/lib/types";
import { money, shortDate } from "@/lib/utils";
import { PageHeading } from "@/components/page-heading";
import { TransactionDialog } from "@/components/transaction-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type PreviousAllocation = { id: string; allocation: string; share_percent: number };
const allocationOptions = ["Shared", "Wife personal", "Your personal", "Needs review"];

function AllocationBadge({ value }: { value: string }) {
  const variant = value === "Needs review" ? "warning" : value === "Shared" ? "info" : value === "Wife personal" ? "secondary" : "outline";
  const label = value === "Wife personal" ? "Wife · 100%" : value === "Your personal" ? "Yours · 0%" : value === "Shared" ? "Shared · 50%" : value;
  return <Badge variant={variant}>{label}</Badge>;
}

export function TransactionsPage() {
  const { transactions, statements, api, applyAllocation, reload, loading } = useLedger();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = React.useState(params.get("search") || "");
  const [status, setStatus] = React.useState(params.get("include") === "all" ? "all" : "review");
  const [kind, setKind] = React.useState("all");
  const [bank, setBank] = React.useState("all");
  const [statement, setStatement] = React.useState(params.get("statement") || "all");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [undo, setUndo] = React.useState<PreviousAllocation[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [edit, setEdit] = React.useState<Transaction | null>(null);
  const [addOpen, setAddOpen] = React.useState(false);
  const [snapshot, setSnapshot] = React.useState<Transaction | null>(null);

  React.useEffect(() => {
    setSearch(params.get("search") || "");
    if (params.get("include") === "all") setStatus("all");
    if (params.get("statement")) setStatement(params.get("statement") || "all");
  }, [params]);

  const visible = React.useMemo(() => transactions.filter((item) => {
    if (status === "review" && item.allocation !== "Needs review" && item.ocr_amount_match !== 0) return false;
    if (status === "allocated" && item.allocation === "Needs review") return false;
    if (kind !== "all" && item.kind !== kind) return false;
    if (bank !== "all" && item.bank !== bank) return false;
    if (statement !== "all" && item.statement_id !== statement) return false;
    const query = search.trim().toLowerCase();
    if (query && ![item.description, item.merchant, item.category, item.bank, item.card_name, item.person].some((part) => String(part || "").toLowerCase().includes(query))) return false;
    return true;
  }), [transactions, status, kind, bank, statement, search]);
  const purchases = visible.filter((item) => item.kind === "Purchase");
  const otherLines = visible.filter((item) => item.kind !== "Purchase");
  const banks = [...new Set(transactions.map((item) => item.bank).filter(Boolean) as string[])].sort();
  const statementName = statements.find((row) => row.id === statement);

  React.useEffect(() => {
    const focusId = params.get("focus");
    if (!focusId || loading) return;
    const timer = window.setTimeout(() => document.querySelector<HTMLElement>(`[data-transaction-row="${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 60);
    return () => window.clearTimeout(timer);
  }, [params, loading, visible.length]);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || (event.key.length !== 1 && event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (target instanceof HTMLElement && target.closest('[role="dialog"], [role="listbox"]')) return;
      const rows = Array.from(document.querySelectorAll<HTMLElement>("[data-transaction-row]"));
      if (!rows.length) return;
      const activeRow = document.activeElement?.closest<HTMLElement>("[data-transaction-row]");
      const currentIndex = rows.indexOf(activeRow || rows[0]);
      const key = event.key.toLowerCase();
      if (key === "arrowdown" || key === "arrowup") {
        event.preventDefault();
        const nextIndex = activeRow ? currentIndex + (key === "arrowdown" ? 1 : -1) : key === "arrowdown" ? 0 : rows.length - 1;
        rows[Math.max(0, Math.min(rows.length - 1, nextIndex))]?.focus({ preventScroll: true });
        return;
      }
      if (!activeRow) return;
      const row = rows[Math.max(0, currentIndex)];
      const id = row?.dataset.transactionRow;
      if (!id) return;
      if (key === "s") void assign([id], "Shared");
      if (key === "w") void assign([id], "Wife personal");
      if (key === "m") void assign([id], "Your personal");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [visible, transactions]);

  function toggleAll(checked: boolean | "indeterminate") {
    setSelected(checked ? visible.map((item) => item.id) : []);
  }
  function toggleOne(id: string, checked: boolean | "indeterminate") {
    setSelected((current) => checked ? [...new Set([...current, id])] : current.filter((item) => item !== id));
  }
  async function assign(ids: string[], allocation: string) {
    const items = ids.map((id) => transactions.find((item) => item.id === id)).filter(Boolean) as Transaction[];
    const allowed = items.filter((item) => item.kind !== "Card payment");
    if (allowed.length !== items.length) toast.message("Card payment lines stay grouped as payments.");
    if (!allowed.length) return;
    setUndo(allowed.map((item) => ({ id: item.id, allocation: item.allocation, share_percent: item.share_percent })));
    await applyAllocation(allowed.map((item) => item.id), allocation);
    setSelected([]);
  }
  async function restore() {
    if (!undo?.length) return;
    setBusy(true);
    try {
      await api("/api/transactions/bulk", { method: "POST", body: JSON.stringify({ items: undo.map((item) => ({ ...item })) }) });
      await reload();
      setUndo(null);
      toast.success("Previous allocations restored");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not undo that change."); }
    finally { setBusy(false); }
  }

  function renderRows(items: Transaction[]) {
    if (!items.length) return <TableRow><TableCell colSpan={8} className="h-28 text-center text-muted-foreground">{loading ? "Loading transactions…" : "No line items match these filters."}</TableCell></TableRow>;
    return items.map((item) => (
      <TableRow key={item.id} data-transaction-row={item.id} tabIndex={0} className="group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
        <TableCell className="w-10"><Checkbox checked={selected.includes(item.id)} onCheckedChange={(checked) => toggleOne(item.id, checked)} aria-label={"Select " + (item.merchant || item.description)} /></TableCell>
        <TableCell className="min-w-64">
          <div className="font-medium">{item.merchant || item.description}</div>
          <div className="mt-0.5 max-w-[340px] truncate text-xs text-muted-foreground">{item.description}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {item.currency && item.currency !== "INR" && <Badge variant="outline" className="h-5 text-[10px]">{item.original_amount} {item.currency}</Badge>}
            {item.ocr_amount_match === 0 && <Badge variant="destructive" className="h-5 text-[10px]">Check INR amount</Badge>}
            {item.suggested_allocation && item.allocation === "Needs review" && <Tooltip><TooltipTrigger asChild><Badge variant="outline" className="h-5 cursor-help text-[10px]">Suggestion</Badge></TooltipTrigger><TooltipContent>{item.suggestion_reason || item.suggested_allocation}</TooltipContent></Tooltip>}
          </div>
        </TableCell>
        <TableCell className="whitespace-nowrap text-muted-foreground">{shortDate(item.date)}</TableCell>
        <TableCell className="text-muted-foreground">{item.person === "Unknown" ? "—" : item.person}</TableCell>
        <TableCell className="min-w-44">
          {item.kind === "Card payment" ? <AllocationBadge value="Card payment" /> : (
            <Select value={item.allocation} onValueChange={(value) => void assign([item.id], value)}>
              <SelectTrigger className="h-8 border-transparent bg-transparent px-2 shadow-none hover:border-input hover:bg-background"><SelectValue /></SelectTrigger>
              <SelectContent>{allocationOptions.map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent>
            </Select>
          )}
        </TableCell>
        <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">{money(item.amount_inr)}</TableCell>
        <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">{money(item.owed_inr)}</TableCell>
        <TableCell><div className="flex justify-end gap-1 opacity-80 group-hover:opacity-100">
          {item.statement_id && item.source_bbox && <Button variant="ghost" size="icon" className="size-8" aria-label="View OCR source line" onClick={() => setSnapshot(item)}><Eye className="size-4" /></Button>}
          <Button variant="ghost" size="icon" className="size-8" aria-label="Edit transaction" onClick={() => setEdit(item)}><PencilLine className="size-4" /></Button>
        </div></TableCell>
      </TableRow>
    ));
  }

  return <>
    <PageHeading title="Transactions" description="Review each statement line and set how it affects the household balance." actions={<><Button variant="outline" asChild><Link to="/statements"><FileText /> Statements</Link></Button><Button onClick={() => setAddOpen(true)}><Plus /> Add transaction</Button></>} />
    {statementName && <Alert className="mb-4"><FileText className="size-4" /><AlertTitle>{statementName.bank} · {statementName.statement_month || statementName.period}</AlertTitle><AlertDescription className="flex flex-wrap items-center justify-between gap-2"><span>Showing line items from this statement.</span><Button variant="ghost" size="sm" onClick={() => { setStatement("all"); setParams({ include: "all" }); }}>Clear statement filter</Button></AlertDescription></Alert>}
    <Card className="mb-4">
      <CardContent className="flex flex-col gap-3 p-3 sm:flex-row sm:flex-wrap sm:items-center sm:p-4">
        <div className="relative min-w-52 flex-1"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search merchant, description…" className="pl-9" /></div>
        <Select value={status} onValueChange={(value) => { setStatus(value); setParams(value === "all" ? { include: "all" } : {}); }}><SelectTrigger className="w-full sm:w-40"><SlidersHorizontal className="mr-2 size-4" /><SelectValue /></SelectTrigger><SelectContent><SelectItem value="review">Needs review</SelectItem><SelectItem value="all">All transactions</SelectItem><SelectItem value="allocated">Allocated</SelectItem></SelectContent></Select>
        <Select value={kind} onValueChange={setKind}><SelectTrigger className="w-full sm:w-40"><SelectValue placeholder="All types" /></SelectTrigger><SelectContent><SelectItem value="all">All types</SelectItem>{[...new Set(transactions.map((item) => item.kind))].map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select>
        <Select value={bank} onValueChange={setBank}><SelectTrigger className="w-full sm:w-40"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All banks</SelectItem>{banks.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select>
        <Select value={statement} onValueChange={setStatement}><SelectTrigger className="w-full sm:w-52"><SelectValue placeholder="All statements" /></SelectTrigger><SelectContent><SelectItem value="all">All statements</SelectItem>{statements.map((row) => <SelectItem key={row.id} value={row.id}>{row.bank} · {row.statement_month || row.period}</SelectItem>)}</SelectContent></Select>
        <span className="px-1 text-xs text-muted-foreground">{visible.length} lines</span>
      </CardContent>
    </Card>
    {undo && <Alert className="mb-4"><RotateCcw className="size-4" /><AlertTitle>Allocation updated</AlertTitle><AlertDescription className="flex flex-wrap items-center justify-between gap-2"><span>You can restore the previous allocation for those line items.</span><Button variant="outline" size="sm" onClick={() => void restore()} disabled={busy}>{busy ? <LoaderCircle className="animate-spin" /> : <RotateCcw />} Undo</Button></AlertDescription></Alert>}
    {selected.length > 0 && <div className="sticky top-[72px] z-20 mb-3 flex flex-wrap items-center gap-2 rounded-lg border bg-popover/95 p-3 shadow-md backdrop-blur">
      <span className="mr-2 text-sm font-medium">{selected.length} selected</span>
      {allocationOptions.slice(0, 3).map((option) => <Button key={option} size="sm" variant={option === "Shared" ? "default" : "outline"} onClick={() => void assign(selected, option)}><Check />{option}</Button>)}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSelected([])}>Clear selection</Button>
    </div>}
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <Table className="min-w-[1080px]"><TableHeader><TableRow><TableHead className="w-10"><Checkbox checked={visible.length > 0 && selected.length === visible.length} onCheckedChange={toggleAll} aria-label="Select all visible line items" /></TableHead><TableHead>Merchant / statement details</TableHead><TableHead>Date</TableHead><TableHead>Made by</TableHead><TableHead>Allocation</TableHead><TableHead className="text-right">Amount</TableHead><TableHead className="text-right">Wife owes</TableHead><TableHead className="w-20" /></TableRow></TableHeader>
          <TableBody>
            {renderRows(purchases)}
            {otherLines.length > 0 && <TableRow className="bg-muted/40 hover:bg-muted/40"><TableCell colSpan={8} className="py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Other statement lines · refunds, payments, fees and interest</TableCell></TableRow>}
            {renderRows(otherLines)}
          </TableBody>
        </Table>
      </div>
    </Card>
    <p className="mt-3 text-xs text-muted-foreground">Shared assigns 50%, wife personal assigns 100%, and your personal assigns 0%. Refunds reduce the same allocated balance. Keyboard: ↑ / ↓ move, S shared, W wife, M yours.</p>
    <TransactionDialog open={!!edit} onOpenChange={(open) => !open && setEdit(null)} transaction={edit} onSaved={() => setEdit(null)} />
    <TransactionDialog open={addOpen} onOpenChange={setAddOpen} />
    <Dialog open={!!snapshot} onOpenChange={(open) => !open && setSnapshot(null)}>
      <DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>Statement line snapshot</DialogTitle><DialogDescription>{snapshot?.description} · Page {snapshot?.source_page || "—"}</DialogDescription></DialogHeader>
        {snapshot && <img className="mx-auto max-h-[60vh] rounded-md border bg-white object-contain" src={"/api/transactions/" + encodeURIComponent(snapshot.id) + "/snapshot"} alt="OCR source line from the statement" />}
      </DialogContent>
    </Dialog>
  </>;
}
