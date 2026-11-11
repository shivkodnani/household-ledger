import * as React from "react";
import { LoaderCircle } from "lucide-react";
import { toast } from "sonner";
import type { Transaction } from "@/lib/types";
import { useLedger } from "@/lib/ledger";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";

const categories = ["Uncategorised", "Groceries", "Dining", "Transport", "Shopping", "Utilities", "Travel", "Health", "Entertainment", "Fees & interest", "Other"];
const kinds = ["Purchase", "Refund", "Card payment", "Fee", "Interest", "Other"];
const allocations = ["Needs review", "Shared", "Wife personal", "Your personal", "Card payment", "Custom"];

type Draft = {
  id?: string;
  date: string;
  description: string;
  merchant_id: string;
  kind: string;
  amount: string;
  original_amount: string;
  currency: string;
  person: string;
  category: string;
  statement_id: string;
  allocation: string;
  share_percent: string;
  payment_method: string;
  notes: string;
};

function emptyDraft(): Draft {
  return {
    date: new Date().toISOString().slice(0, 10),
    description: "",
    merchant_id: "",
    kind: "Purchase",
    amount: "",
    original_amount: "",
    currency: "INR",
    person: "Unknown",
    category: "Uncategorised",
    statement_id: "",
    allocation: "Needs review",
    share_percent: "0",
    payment_method: "Credit card",
    notes: "",
  };
}

function draftFor(transaction?: Transaction | null): Draft {
  if (!transaction) return emptyDraft();
  return {
    id: transaction.id,
    date: transaction.date,
    description: transaction.description,
    merchant_id: transaction.merchant_id || "",
    kind: transaction.kind,
    amount: String(Math.abs(Number(transaction.amount_inr || 0))),
    original_amount: transaction.original_amount == null ? "" : String(transaction.original_amount),
    currency: transaction.currency || "INR",
    person: transaction.person || "Unknown",
    category: transaction.category || "Uncategorised",
    statement_id: transaction.statement_id || "",
    allocation: transaction.allocation || "Needs review",
    share_percent: String(transaction.share_percent || 0),
    payment_method: transaction.payment_method || "Credit card",
    notes: transaction.notes || "",
  };
}

export function TransactionDialog({
  open,
  onOpenChange,
  transaction,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transaction?: Transaction | null;
  onSaved?: () => void;
}) {
  const { api, merchants, statements, reload } = useLedger();
  const [draft, setDraft] = React.useState<Draft>(() => draftFor(transaction));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setDraft(draftFor(transaction));
      setBusy(false);
      setError("");
    }
  }, [open, transaction]);

  function patch(values: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...values }));
  }

  function changeKind(kind: string) {
    patch({
      kind,
      allocation: kind === "Card payment" ? "Card payment" : draft.allocation === "Card payment" ? "Needs review" : draft.allocation,
    });
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const amount = Math.abs(Number(draft.amount || 0));
      const payload = {
        id: draft.id,
        date: draft.date,
        description: draft.description,
        merchant_id: draft.merchant_id || null,
        kind: draft.kind,
        amount_inr: draft.kind === "Refund" ? -amount : amount,
        original_amount: draft.original_amount === "" ? null : Number(draft.original_amount),
        currency: draft.currency,
        person: draft.person,
        category: draft.category,
        statement_id: draft.statement_id || null,
        allocation: draft.allocation,
        share_percent: Number(draft.share_percent || 0),
        payment_method: draft.payment_method,
        notes: draft.notes,
      };
      await api(draft.id ? "/api/transactions/" + encodeURIComponent(draft.id) : "/api/transactions", {
        method: draft.id ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      void reload();
      onOpenChange(false);
      onSaved?.();
      toast.success(draft.id ? "Transaction updated" : "Transaction added");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save this transaction.");
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{draft.id ? "Edit transaction" : "Add transaction"}</DialogTitle>
          <DialogDescription>Keep the statement value intact, then choose how this line should affect the household balance.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-5">
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="tx-date">Date</Label><Input id="tx-date" type="date" required value={draft.date} onChange={(e) => patch({ date: e.target.value })} /></div>
            <div className="space-y-2"><Label>Type</Label><Select value={draft.kind} onValueChange={changeKind}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{kinds.map((kind) => <SelectItem key={kind} value={kind}>{kind}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2 sm:col-span-2"><Label htmlFor="tx-description">Statement description</Label><Input id="tx-description" required placeholder="e.g. BUNDL TECHNOLOGIES PVT LTD" value={draft.description} onChange={(e) => patch({ description: e.target.value })} /></div>
            <div className="space-y-2"><Label>Merchant match</Label><Select value={draft.merchant_id || "none"} onValueChange={(value) => patch({ merchant_id: value === "none" ? "" : value })}><SelectTrigger><SelectValue placeholder="No merchant match" /></SelectTrigger><SelectContent><SelectItem value="none">No merchant match</SelectItem>{merchants.map((merchant) => <SelectItem key={merchant.id} value={merchant.id}>{merchant.display_name}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label>Category</Label><Select value={draft.category} onValueChange={(value) => patch({ category: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{categories.map((category) => <SelectItem key={category} value={category}>{category}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label htmlFor="tx-amount">Statement amount (INR)</Label><Input id="tx-amount" type="number" step="0.01" min="0" required placeholder="0.00" value={draft.amount} onChange={(e) => patch({ amount: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="tx-original">Original currency amount</Label><Input id="tx-original" type="number" step="0.01" placeholder="Optional" value={draft.original_amount} onChange={(e) => patch({ original_amount: e.target.value })} /></div>
            <div className="space-y-2"><Label>Original currency</Label><Select value={draft.currency} onValueChange={(value) => patch({ currency: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["INR", "USD", "EUR", "GBP", "AED", "SGD", "DKK", "Other"].map((currency) => <SelectItem key={currency} value={currency}>{currency}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label>Made by</Label><Select value={draft.person} onValueChange={(value) => patch({ person: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["Unknown", "Me", "Wife"].map((person) => <SelectItem key={person} value={person}>{person}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label>Source statement</Label><Select value={draft.statement_id || "manual"} onValueChange={(value) => patch({ statement_id: value === "manual" ? "" : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="manual">Manual / no statement</SelectItem>{statements.map((statement) => <SelectItem key={statement.id} value={statement.id}>{statement.bank} · {statement.statement_month || statement.period}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label>Allocation</Label><Select value={draft.kind === "Card payment" ? "Card payment" : draft.allocation} onValueChange={(value) => patch({ allocation: value })} disabled={draft.kind === "Card payment"}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{allocations.map((allocation) => <SelectItem key={allocation} value={allocation}>{allocation}</SelectItem>)}</SelectContent></Select></div>
            {draft.allocation === "Custom" && draft.kind !== "Card payment" && <div className="space-y-2"><Label htmlFor="tx-share">Wife’s share (%)</Label><Input id="tx-share" type="number" min="0" max="100" step="0.1" value={draft.share_percent} onChange={(e) => patch({ share_percent: e.target.value })} /></div>}
            <div className="space-y-2"><Label>Paid via</Label><Select value={draft.payment_method} onValueChange={(value) => patch({ payment_method: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["Credit card", "Cash", "Savings account", "Other"].map((method) => <SelectItem key={method} value={method}>{method}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2 sm:col-span-2"><Label htmlFor="tx-notes">Notes</Label><Textarea id="tx-notes" rows={2} placeholder="Optional context" value={draft.notes} onChange={(e) => patch({ notes: e.target.value })} /></div>
          </div>
          <Alert className="text-xs">
            <AlertDescription>Shared adds 50% to what your wife owes. Her personal adds 100%; your personal adds 0%. Refunds reduce the balance.</AlertDescription>
          </Alert>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy}>{busy && <LoaderCircle className="animate-spin" />}{busy ? "Saving…" : "Save transaction"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
