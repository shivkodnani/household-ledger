import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowUpRight, CheckCircle2, FileText, LoaderCircle, Plus, Upload } from "lucide-react";
import { toast } from "sonner";
import type { Statement } from "@/lib/types";
import { money, monthLabel } from "@/lib/utils";
import { useLedger } from "@/lib/ledger";
import { PageHeading } from "@/components/page-heading";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const banks = ["HSBC", "ICICI", "HDFC", "Amex"];
const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function statementMonth(statement: Statement) {
  return statement.statement_month && /^\d{4}-\d{2}$/.test(statement.statement_month)
    ? monthLabel(statement.statement_month)
    : statement.period || statement.filename;
}

function periodText(value: string) {
  if (!/^\d{4}-\d{2}$/.test(value)) return value;
  const [year, month] = value.split("-").map(Number);
  return monthNames[month - 1] + " " + year;
}

function StatusBadge({ statement }: { statement: Statement }) {
  if (statement.reconciliation_status === "matched") return <Badge variant="success"><CheckCircle2 /> Reconciled</Badge>;
  if (statement.reconciliation_status === "needs attention") return <Badge variant="warning"><AlertTriangle /> Check totals</Badge>;
  if (statement.extraction_status === "error") return <Badge variant="destructive">Extraction issue</Badge>;
  if (statement.extraction_status === "empty") return <Badge variant="outline">No transactions found</Badge>;
  return <Badge variant="secondary">{statement.extraction_status || "Uploaded"}</Badge>;
}

export function StatementsPage() {
  const { statements, api, reload, loading } = useLedger();
  const [params] = useSearchParams();
  const [open, setOpen] = React.useState(false);
  const [bank, setBank] = React.useState("HSBC");
  const [cardName, setCardName] = React.useState("");
  const [period, setPeriod] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [filterBank, setFilterBank] = React.useState("all");
  const search = params.get("search") || "";
  const visible = statements.filter((item) => (filterBank === "all" || item.bank === filterBank) && (!search || [item.filename, item.bank, item.card_name, item.period, item.statement_month].some((value) => String(value || "").toLowerCase().includes(search.toLowerCase()))));

  React.useEffect(() => {
    const focusId = params.get("focus");
    if (!focusId || loading) return;
    const timer = window.setTimeout(() => document.querySelector<HTMLElement>(`[data-statement-row="${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 60);
    return () => window.clearTimeout(timer);
  }, [params, loading]);

  function resetForm() {
    setBank("HSBC"); setCardName(""); setPeriod(""); setFile(null); setError(""); setBusy(false);
  }
  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) { setError("Choose a PDF statement first."); return; }
    setBusy(true); setError("");
    try {
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("Could not read the selected PDF."));
        reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
        reader.readAsDataURL(file);
      });
      const result = await api<{ id: string; extraction_status: string; transaction_count: number; pages: number; message?: string; reconciliation_status?: string }>("/api/statements", {
        method: "POST",
        body: JSON.stringify({ bank, card_name: cardName.trim(), period: periodText(period), filename: file.name, data }),
      });
      setOpen(false); resetForm();
      void reload();
      const detail = bank === "HSBC" ? `${result.transaction_count} transaction lines extracted` : "PDF saved for your records";
      toast.success("Statement uploaded", { description: result.message || detail });
      // Merchant discovery runs on the server after statement processing. Refresh its review queue later without delaying upload.
      window.setTimeout(() => { void reload(); }, 1800);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Statement upload failed.");
      setBusy(false);
    }
  }

  return <>
    <PageHeading title="Statements" description="Keep statement PDFs alongside the structured transactions extracted for your analytics." actions={<Dialog open={open} onOpenChange={(value) => { setOpen(value); if (!value) resetForm(); }}>
      <DialogTrigger asChild><Button><Plus /> Upload statement</Button></DialogTrigger>
      <DialogContent className="max-w-xl"><DialogHeader><DialogTitle>Upload a statement PDF</DialogTitle><DialogDescription>HSBC statements are itemized automatically. Other banks are stored as source PDFs for now.</DialogDescription></DialogHeader>
        <form className="space-y-4" onSubmit={(event) => void upload(event)}>
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2"><Label>Bank</Label><Select value={bank} onValueChange={setBank}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{banks.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label htmlFor="statement-card">Card label</Label><Input id="statement-card" value={cardName} onChange={(event) => setCardName(event.target.value)} placeholder="e.g. HSBC Cashback" /></div>
            <div className="space-y-2 sm:col-span-2"><Label htmlFor="statement-period">Statement month</Label><Input id="statement-period" type="month" required value={period} onChange={(event) => setPeriod(event.target.value)} /></div>
            <div className="space-y-2 sm:col-span-2"><Label htmlFor="statement-pdf">PDF file</Label><Input id="statement-pdf" type="file" accept="application/pdf,.pdf" required onChange={(event) => setFile(event.target.files?.[0] || null)} /><p className="text-xs text-muted-foreground">For hosted uploads, keep the PDF under 3 MB.</p></div>
          </div>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={busy}>Cancel</Button><Button type="submit" disabled={busy || !file}>{busy ? <><LoaderCircle className="animate-spin" /> Processing statement…</> : <><Upload /> Upload and process</>}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>} />
    <div className="mb-4 flex flex-wrap items-center gap-3"><Select value={filterBank} onValueChange={setFilterBank}><SelectTrigger className="w-44"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All banks</SelectItem>{banks.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent></Select><span className="text-xs text-muted-foreground">{visible.length} statements</span></div>
    {statements.some((item) => item.reconciliation_status === "needs attention") && <Alert variant="warning" className="mb-4"><AlertTriangle className="size-4" /><AlertTitle>Some statement totals need a review</AlertTitle><AlertDescription>Open the related transactions and compare the extracted INR totals with the amount shown on the PDF.</AlertDescription></Alert>}
    <Card className="overflow-hidden"><div className="overflow-x-auto"><Table className="min-w-[850px]"><TableHeader><TableRow><TableHead>Statement</TableHead><TableHead>Bank / card</TableHead><TableHead>Transactions</TableHead><TableHead>Extracted INR</TableHead><TableHead>Reconciliation</TableHead><TableHead>Uploaded</TableHead><TableHead className="text-right">Links</TableHead></TableRow></TableHeader><TableBody>
      {visible.length ? visible.map((item) => <TableRow key={item.id} data-statement-row={item.id}>
        <TableCell><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-muted"><FileText className="size-4 text-muted-foreground" /></span><div><p className="font-medium">{statementMonth(item)}</p><p className="max-w-56 truncate text-xs text-muted-foreground" title={item.filename}>{item.filename}</p></div></div></TableCell>
        <TableCell><p className="font-medium">{item.bank}</p><p className="text-xs text-muted-foreground">{item.card_name || "Credit card"}</p></TableCell>
        <TableCell>{item.transaction_count ?? 0}</TableCell>
        <TableCell className="tabular-nums">{item.extracted_charges_inr == null ? "—" : money(item.extracted_charges_inr)}</TableCell>
        <TableCell><StatusBadge statement={item} />{item.reconciliation_status === "needs attention" && <p className="mt-1 text-xs text-muted-foreground">Off by {money(Math.abs(Number(item.reconciliation_difference_inr || 0)))}</p>}</TableCell>
        <TableCell className="whitespace-nowrap text-muted-foreground">{new Date(item.uploaded_at).toLocaleDateString()}</TableCell>
        <TableCell><div className="flex justify-end gap-1"><Button variant="outline" size="sm" asChild><a href={"/files/" + encodeURIComponent(item.id)} target="_blank" rel="noreferrer">PDF <ArrowUpRight /></a></Button><Button variant="ghost" size="sm" asChild><Link to={"/transactions?statement=" + encodeURIComponent(item.id) + "&include=all"}>Transactions <ArrowUpRight /></Link></Button></div></TableCell>
      </TableRow>) : <TableRow><TableCell colSpan={7} className="h-52 text-center"><div className="mx-auto max-w-sm"><div className="mx-auto mb-3 grid size-11 place-items-center rounded-xl bg-muted"><FileText className="size-5 text-muted-foreground" /></div><p className="font-medium">{loading ? "Loading statements…" : "No statements yet"}</p><p className="mt-1 text-sm text-muted-foreground">Upload your first PDF to create a structured transaction history.</p></div></TableCell></TableRow>}
    </TableBody></Table></div></Card>
  </>;
}
