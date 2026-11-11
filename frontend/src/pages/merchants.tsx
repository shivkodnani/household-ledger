import * as React from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, ExternalLink, LoaderCircle, Plus, RefreshCw, Search, Store } from "lucide-react";
import { toast } from "sonner";
import type { Merchant, MerchantDiscovery } from "@/lib/types";
import { useLedger } from "@/lib/ledger";
import { PageHeading } from "@/components/page-heading";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

type MerchantDraft = { id?: string; display_name: string; legal_name: string; aliases: string; category: string; allocation_suggestion: string; suggestion_person: string };
const categories = ["Uncategorised", "Groceries", "Dining", "Transport", "Shopping", "Utilities", "Travel", "Health", "Entertainment", "Fees & interest", "Other"];

function blankDraft(): MerchantDraft { return { display_name: "", legal_name: "", aliases: "", category: "Uncategorised", allocation_suggestion: "", suggestion_person: "Any" }; }
function toDraft(merchant?: Merchant): MerchantDraft {
  if (!merchant) return blankDraft();
  return { id: merchant.id, display_name: merchant.display_name, legal_name: merchant.legal_name || "", aliases: (merchant.aliases || []).join("\n"), category: merchant.category || "Uncategorised", allocation_suggestion: merchant.allocation_suggestion || "", suggestion_person: merchant.suggestion_person || "Any" };
}

export function MerchantsPage() {
  const { merchants, discoveries, discoveryMeta, api, reload, loadDiscoveries } = useLedger();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = React.useState(params.get("search") || "");
  const [draft, setDraft] = React.useState<MerchantDraft | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [review, setReview] = React.useState<MerchantDiscovery | null>(null);
  const [brand, setBrand] = React.useState("");
  const [legal, setLegal] = React.useState("");
  const [selectedResult, setSelectedResult] = React.useState("0");
  const [selectedMerchant, setSelectedMerchant] = React.useState("");
  const [searching, setSearching] = React.useState(false);
  const visibleMerchants = merchants.filter((merchant) => [merchant.display_name, merchant.legal_name, ...(merchant.aliases || [])].some((value) => String(value || "").toLowerCase().includes(query.toLowerCase())));
  const searchingQueue = discoveries.some((item) => ["searching", "pending"].includes(item.status));

  React.useEffect(() => {
    if (!searchingQueue) return;
    const timer = window.setInterval(() => { void loadDiscoveries(); }, 2500);
    return () => window.clearInterval(timer);
  }, [searchingQueue, loadDiscoveries]);

  React.useEffect(() => {
    setQuery(params.get("search") || "");
    const focusId = params.get("focus");
    if (!focusId) return;
    const timer = window.setTimeout(() => document.querySelector<HTMLElement>(`[data-merchant-card="${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 60);
    return () => window.clearTimeout(timer);
  }, [params]);

  function openReview(item: MerchantDiscovery) {
    setReview(item); setBrand(item.results?.[0]?.suggested_brand_name || item.raw_alias); setLegal(item.results?.[0]?.suggested_legal_name || ""); setSelectedResult("0"); setSelectedMerchant(item.results?.find((result) => result.merchant_id)?.merchant_id || "");
  }
  async function saveMerchant(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!draft) return;
    setBusy(true);
    const payload = { display_name: draft.display_name, legal_name: draft.legal_name, aliases: draft.aliases.split(/\n|,/).map((item) => item.trim()).filter(Boolean), category: draft.category, allocation_suggestion: draft.allocation_suggestion, suggestion_person: draft.suggestion_person };
    try {
      await api(draft.id ? "/api/merchants/" + encodeURIComponent(draft.id) : "/api/merchants", { method: draft.id ? "PUT" : "POST", body: JSON.stringify(payload) });
      setDraft(null); void reload(); toast.success(draft.id ? "Merchant updated" : "Merchant added");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not save merchant."); }
    finally { setBusy(false); }
  }
  async function reviewAction(action: "approve" | "reject", merchantId?: string) {
    if (!review) return;
    setBusy(true);
    try {
      const body = action === "approve" ? review.status === "close_match" ? { merchant_id: merchantId || selectedMerchant } : { brand_name: brand, legal_name: legal, result_index: Number(selectedResult) } : {};
      await api(`/api/merchant-discoveries/${encodeURIComponent(review.id)}/${action}`, { method: "POST", body: JSON.stringify(body) });
      setReview(null); void Promise.all([loadDiscoveries(), reload()]); toast.success(action === "approve" ? "Merchant match approved" : "Suggestion rejected");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not save your decision."); }
    finally { setBusy(false); }
  }
  async function rejectSuggestion(item: MerchantDiscovery) {
    try {
      await api(`/api/merchant-discoveries/${encodeURIComponent(item.id)}/reject`, { method: "POST", body: JSON.stringify({}) });
      await loadDiscoveries();
      toast.success("Suggestion rejected");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not reject suggestion."); }
  }
  async function runSearch(path = "/api/merchant-discoveries/search") {
    setSearching(true);
    try {
      const result = await api<{ queued: number }>(path, { method: "POST", body: JSON.stringify({}) });
      await loadDiscoveries(); toast.success(result.queued ? "Merchant searches queued" : "No new merchants to search");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not start merchant search."); }
    finally { setSearching(false); }
  }
  async function discoveryAction(item: MerchantDiscovery, action: "retry" | "search-as-new") {
    try { await api(`/api/merchant-discoveries/${encodeURIComponent(item.id)}/${action}`, { method: "POST", body: JSON.stringify({}) }); await loadDiscoveries(); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not start this search."); }
  }

  function discoveryCard(item: MerchantDiscovery) {
    const isClose = item.status === "close_match";
    const actionable = item.status === "review" || isClose;
    return <Card key={item.id} className="transition-shadow hover:shadow-md"><CardHeader className="pb-3"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><CardTitle className="break-words text-base">{item.raw_alias}</CardTitle><CardDescription className="mt-1">Seen {item.transaction_count} time{item.transaction_count === 1 ? "" : "s"} · {item.status.replace(/_/g, " ")}</CardDescription></div><Badge variant={isClose ? "warning" : item.status === "failed" ? "destructive" : item.status === "searching" ? "info" : "secondary"}>{item.status === "searching" ? <LoaderCircle className="animate-spin" /> : null}{item.status.replace(/_/g, " ")}</Badge></div></CardHeader><CardContent className="space-y-3">
      {item.status === "review" && item.results?.slice(0, 2).map((result, index) => <div key={result.url || result.title} className="rounded-lg border bg-muted/20 p-3"><p className="font-medium text-sm">{result.suggested_brand_name || result.title}</p>{result.suggested_legal_name && <p className="mt-0.5 text-xs text-muted-foreground">{result.suggested_legal_name}</p>}<p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{result.description}</p><a href={result.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline">Source <ExternalLink className="size-3" /></a>{index === 0 && <span className="sr-only">Top result</span>}</div>)}
      {item.status === "close_match" && item.results?.map((result) => <button key={result.merchant_id || result.title} type="button" onClick={() => setSelectedMerchant(result.merchant_id || "")} className={'flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors ' + (selectedMerchant === result.merchant_id ? "border-primary bg-accent" : "hover:bg-accent/50")}><span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted"><Store className="size-4" /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{result.suggested_brand_name || result.title}</span><span className="block text-xs text-muted-foreground">Match score {Math.round((result.match_score || 0) * 100)}%</span></span>{selectedMerchant === result.merchant_id && <CheckCircle2 className="size-4 text-primary" />}</button>)}
      {item.search_error && <p className="text-xs text-destructive">{item.search_error}</p>}
      <Separator />
      <div className="flex flex-wrap justify-end gap-2">{actionable && <Button size="sm" onClick={() => openReview(item)}>{isClose ? "Review possible match" : "Review result"}</Button>}{item.status === "failed" || item.status === "no_results" ? <Button size="sm" variant="outline" onClick={() => void discoveryAction(item, "retry")}><RefreshCw /> Retry</Button> : null}{isClose && <Button size="sm" variant="outline" onClick={() => void discoveryAction(item, "search-as-new")}>Search as new</Button>}{item.status !== "searching" && item.status !== "pending" && <Button size="sm" variant="ghost" onClick={() => void rejectSuggestion(item)} disabled={busy} aria-label="Reject suggestion">Reject</Button>}</div>
    </CardContent></Card>;
  }

  return <>
    <PageHeading title="Merchants" description="Build a reusable merchant directory from statement aliases and reviewed web matches." actions={<Button onClick={() => setDraft(blankDraft())}><Plus /> Add merchant</Button>} />
    <Tabs defaultValue="directory" className="space-y-4">
      <TabsList><TabsTrigger value="directory">Directory <Badge variant="secondary" className="ml-2">{merchants.length}</Badge></TabsTrigger><TabsTrigger value="review">Suggestions <Badge variant="secondary" className="ml-2">{discoveries.length}</Badge></TabsTrigger></TabsList>
      <TabsContent value="directory" className="space-y-4">
        <div className="relative max-w-md"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input value={query} onChange={(event) => { setQuery(event.target.value); setParams(event.target.value ? { search: event.target.value } : {}); }} placeholder="Search name or statement alias" className="pl-9" /></div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{visibleMerchants.map((merchant) => <Card key={merchant.id} role="button" tabIndex={0} data-merchant-card={merchant.id} aria-label={"Edit merchant " + merchant.display_name} className="cursor-pointer transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setDraft(toDraft(merchant))} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setDraft(toDraft(merchant)); } }}><CardHeader className="pb-2"><div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-muted"><Store className="size-5 text-muted-foreground" /></span><div className="min-w-0"><CardTitle className="truncate text-base">{merchant.display_name}</CardTitle><CardDescription className="truncate">{merchant.legal_name || merchant.category}</CardDescription></div></div></CardHeader><CardContent><div className="flex flex-wrap gap-1.5">{(merchant.aliases || []).slice(0, 5).map((alias) => <Badge key={alias} variant="outline" className="font-normal">{alias}</Badge>)}{(merchant.aliases || []).length > 5 && <Badge variant="secondary">+{merchant.aliases.length - 5}</Badge>}</div>{merchant.allocation_suggestion && <p className="mt-3 text-xs text-muted-foreground">Allocation suggestion: {merchant.allocation_suggestion}{merchant.suggestion_person && merchant.suggestion_person !== "Any" ? ` · ${merchant.suggestion_person}` : ""}</p>}</CardContent></Card>)}{visibleMerchants.length === 0 && <Card className="md:col-span-2 xl:col-span-3"><CardContent className="grid min-h-40 place-items-center text-center"><div><p className="font-medium">No merchants found</p><p className="mt-1 text-sm text-muted-foreground">Add a merchant or adjust your search.</p></div></CardContent></Card>}</div>
      </TabsContent>
      <TabsContent value="review" className="space-y-4">
        <Alert><Search className="size-4" /><AlertDescription className="flex flex-wrap items-center justify-between gap-3"><span>Exact and close matches stay out of web search. New aliases are searched in the background and wait here for your approval.</span><Button size="sm" variant="outline" onClick={() => void runSearch()} disabled={searching || !discoveryMeta.search_available}>{searching ? <LoaderCircle className="animate-spin" /> : <RefreshCw />} Search pending aliases</Button></AlertDescription></Alert>
        {!discoveryMeta.search_available && discoveries.some((item) => item.status === "pending") && <Alert variant="warning"><AlertDescription>Web search is not available in the server configuration right now. Pending aliases stay safely queued.</AlertDescription></Alert>}
        {discoveries.length ? <div className="grid gap-3 xl:grid-cols-2">{discoveries.map(discoveryCard)}</div> : <Card><CardContent className="grid min-h-48 place-items-center text-center"><div><p className="font-medium">No merchant suggestions to review</p><p className="mt-1 text-sm text-muted-foreground">New statement aliases that need research will appear here.</p></div></CardContent></Card>}
      </TabsContent>
    </Tabs>
    <Dialog open={!!draft} onOpenChange={(open) => !open && setDraft(null)}><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>{draft?.id ? "Edit merchant" : "Add merchant"}</DialogTitle><DialogDescription>Keep the familiar brand name and statement spellings together for future matching.</DialogDescription></DialogHeader>{draft && <form className="space-y-4" onSubmit={(event) => void saveMerchant(event)}><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label>Brand name</Label><Input required value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} /></div><div className="space-y-2"><Label>Legal name</Label><Input value={draft.legal_name} onChange={(e) => setDraft({ ...draft, legal_name: e.target.value })} /></div><div className="space-y-2 sm:col-span-2"><Label>Statement aliases</Label><Textarea rows={4} placeholder={'BUNDL\nSWIGGY'} value={draft.aliases} onChange={(e) => setDraft({ ...draft, aliases: e.target.value })} /><p className="text-xs text-muted-foreground">One alias per line; matching uses approved aliases against statement descriptions.</p></div><div className="space-y-2"><Label>Category</Label><Select value={draft.category} onValueChange={(value) => setDraft({ ...draft, category: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{categories.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></div><div className="space-y-2"><Label>Suggested allocation</Label><Select value={draft.allocation_suggestion || "none"} onValueChange={(value) => setDraft({ ...draft, allocation_suggestion: value === "none" ? "" : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">No suggestion</SelectItem>{["Shared", "Wife personal", "Your personal"].map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></div><div className="space-y-2"><Label>Usually purchased by</Label><Select value={draft.suggestion_person} onValueChange={(value) => setDraft({ ...draft, suggestion_person: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["Any", "Me", "Wife"].map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></div></div><DialogFooter><Button variant="outline" type="button" onClick={() => setDraft(null)}>Cancel</Button><Button disabled={busy}>{busy && <LoaderCircle className="animate-spin" />}Save merchant</Button></DialogFooter></form>}</DialogContent></Dialog>
    <Dialog open={!!review} onOpenChange={(open) => !open && setReview(null)}><DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto"><DialogHeader><DialogTitle>Review “{review?.raw_alias}”</DialogTitle><DialogDescription>Check the evidence and approve the reusable merchant match, or reject it.</DialogDescription></DialogHeader>{review?.status === "close_match" ? <div className="space-y-2">{review.results?.map((result) => <button key={result.merchant_id || result.title} type="button" onClick={() => setSelectedMerchant(result.merchant_id || "")} className={'flex w-full items-center gap-3 rounded-lg border p-3 text-left ' + (selectedMerchant === result.merchant_id ? "border-primary bg-accent" : "hover:bg-accent/50")}><span className={'grid size-5 place-items-center rounded-full border ' + (selectedMerchant === result.merchant_id ? "border-primary text-primary" : "border-muted-foreground/40")}>{selectedMerchant === result.merchant_id && <span className="size-2.5 rounded-full bg-primary" />}</span><span><span className="block font-medium">{result.suggested_brand_name || result.title}</span><span className="text-xs text-muted-foreground">Match score {Math.round((result.match_score || 0) * 100)}%</span></span></button>)}</div> : <div className="space-y-3">{review?.results?.map((result, index) => <div key={result.url || result.title} className={'rounded-lg border p-3 ' + (selectedResult === String(index) ? "border-primary bg-accent/40" : "hover:bg-accent/30")}><label className="flex cursor-pointer items-start gap-3"><input type="radio" name="discovery-result" checked={selectedResult === String(index)} onChange={() => { setSelectedResult(String(index)); if (!brand || brand === review.raw_alias) setBrand(result.suggested_brand_name || ""); setLegal(result.suggested_legal_name || ""); }} className="mt-1 accent-primary" /><span className="min-w-0"><span className="block font-medium">{result.title}</span><span className="mt-1 block text-sm text-muted-foreground">{result.description}</span></span></label><a href={result.url} target="_blank" rel="noreferrer" className="ml-6 mt-2 inline-flex items-center gap-1 text-xs text-primary">Open source <ExternalLink className="size-3" /></a></div>)}<div className="grid gap-3 sm:grid-cols-2"><div className="space-y-2"><Label>Approved brand name</Label><Input value={brand} onChange={(e) => setBrand(e.target.value)} /></div><div className="space-y-2"><Label>Legal name</Label><Input value={legal} onChange={(e) => setLegal(e.target.value)} /></div></div></div>}<DialogFooter className="gap-2 sm:justify-between"><Button variant="ghost" onClick={() => void reviewAction("reject")} disabled={busy}>Reject suggestion</Button><div className="flex gap-2"><Button variant="outline" onClick={() => setReview(null)}>Cancel</Button><Button onClick={() => void reviewAction("approve")} disabled={busy || (review?.status === "close_match" && !selectedMerchant)}>{busy && <LoaderCircle className="animate-spin" />}Approve match</Button></div></DialogFooter></DialogContent></Dialog>
  </>;
}
