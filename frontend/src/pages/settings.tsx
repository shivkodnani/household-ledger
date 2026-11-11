import * as React from "react";
import { Download, FileDown, KeyRound, LoaderCircle, Plus, RefreshCw, Shield, Trash2, Users } from "lucide-react";
import { toast } from "sonner";
import { useLedger } from "@/lib/ledger";
import type { User } from "@/lib/types";
import { credentialPayload, registrationOptionsFromJSON } from "@/lib/passkeys";
import { PageHeading } from "@/components/page-heading";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

function initials(name?: string) { return (name || "U").split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase(); }

export function SettingsPage() {
  const { auth, adminUsers, backupMeta, api, loadPasskeys, reload } = useLedger();
  const [passkeys, setPasskeys] = React.useState<Awaited<ReturnType<typeof loadPasskeys>>>([]);
  const [passkeysLoading, setPasskeysLoading] = React.useState(false);
  const [passkeyName, setPasskeyName] = React.useState("iCloud Keychain");
  const [passkeyBusy, setPasskeyBusy] = React.useState(false);
  const [passkeyAvailable, setPasskeyAvailable] = React.useState(true);
  const [removePasskeyTarget, setRemovePasskeyTarget] = React.useState<{ id: string; nickname: string } | null>(null);
  const [passwordBusy, setPasswordBusy] = React.useState(false);
  const [passwords, setPasswords] = React.useState({ current_password: "", new_password: "", confirm_password: "" });
  const [newUserOpen, setNewUserOpen] = React.useState(false);
  const [newUser, setNewUser] = React.useState({ display_name: "", email: "", password: "", role: "user" });
  const [createUserBusy, setCreateUserBusy] = React.useState(false);
  const [resetUser, setResetUser] = React.useState<User | null>(null);
  const [resetPassword, setResetPassword] = React.useState("");
  const [resetBusy, setResetBusy] = React.useState(false);
  const [backupBusy, setBackupBusy] = React.useState(false);
  const isAdmin = auth?.user?.role === "admin";

  React.useEffect(() => {
    if (!auth?.auth_required || !auth.authenticated) return;
    setPasskeysLoading(true);
    loadPasskeys().then(setPasskeys).catch((error) => toast.error(error instanceof Error ? error.message : "Could not load passkeys.")).finally(() => setPasskeysLoading(false));
  }, [auth?.auth_required, auth?.authenticated, loadPasskeys]);

  async function addPasskey() {
    if (!window.PublicKeyCredential || !navigator.credentials?.create) { setPasskeyAvailable(false); return; }
    setPasskeyBusy(true);
    try {
      const options = await api<{ challenge_id: string; public_key: PublicKeyCredentialCreationOptions }>("/api/auth/passkeys/options", { method: "POST", body: JSON.stringify({ nickname: passkeyName.trim() || "Passkey" }) });
      const credential = await navigator.credentials.create({ publicKey: registrationOptionsFromJSON(options.public_key) });
      if (!credential || !(credential instanceof PublicKeyCredential)) throw new Error("Passkey setup was cancelled.");
      await api("/api/auth/passkeys/verify", { method: "POST", body: JSON.stringify({ challenge_id: options.challenge_id, credential: credentialPayload(credential, true) }) });
      toast.success("Passkey added", { description: "If prompted on an Apple device, choose iCloud Keychain to sync it." });
      void loadPasskeys().then(setPasskeys).catch(() => {});
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not add passkey."); }
    finally { setPasskeyBusy(false); }
  }
  async function renamePasskey(id: string, nickname: string) {
    try { await api("/api/auth/passkeys/" + encodeURIComponent(id), { method: "PUT", body: JSON.stringify({ nickname }) }); setPasskeys((current) => current.map((item) => item.id === id ? { ...item, nickname } : item)); toast.success("Passkey name saved"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not rename passkey."); }
  }
  async function removePasskey() {
    if (!removePasskeyTarget) return;
    setPasskeyBusy(true);
    try { await api("/api/auth/passkeys/" + encodeURIComponent(removePasskeyTarget.id), { method: "DELETE" }); setPasskeys((current) => current.filter((item) => item.id !== removePasskeyTarget.id)); setRemovePasskeyTarget(null); toast.success("Passkey removed"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not remove passkey."); }
    finally { setPasskeyBusy(false); }
  }
  async function changePassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (passwords.new_password !== passwords.confirm_password) { toast.error("The new passwords do not match."); return; }
    setPasswordBusy(true);
    try { await api("/api/auth/password", { method: "POST", body: JSON.stringify({ current_password: passwords.current_password, new_password: passwords.new_password }) }); toast.success("Password changed", { description: "Sign in again with your new password." }); window.location.assign("/login"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not change password."); }
    finally { setPasswordBusy(false); }
  }
  async function createUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setCreateUserBusy(true);
    try { await api("/api/admin/users", { method: "POST", body: JSON.stringify(newUser) }); void reload(); setNewUserOpen(false); setNewUser({ display_name: "", email: "", password: "", role: "user" }); toast.success("Household account created"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not create account."); }
    finally { setCreateUserBusy(false); }
  }
  async function updateUser(user: User, changes: Partial<User>) {
    try { await api("/api/admin/users/" + encodeURIComponent(user.id), { method: "PUT", body: JSON.stringify({ display_name: changes.display_name ?? user.display_name, role: changes.role ?? user.role, active: changes.active ?? user.active }) }); void reload(); toast.success("Account access updated"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not update account."); }
  }
  async function saveReset(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!resetUser) return; setResetBusy(true);
    try { await api("/api/admin/users/" + encodeURIComponent(resetUser.id) + "/password", { method: "POST", body: JSON.stringify({ password: resetPassword }) }); setResetUser(null); setResetPassword(""); toast.success("Password reset; previous sessions ended"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not reset password."); }
    finally { setResetBusy(false); }
  }
  async function createBackup() {
    setBackupBusy(true);
    try { await api("/api/admin/backups", { method: "POST", body: JSON.stringify({}) }); void reload(); toast.success("Encrypted backup created"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not create backup."); }
    finally { setBackupBusy(false); }
  }
  async function exportData() {
    try { const data = await api("/api/export"); const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = "household-ledger-export.json"; anchor.click(); URL.revokeObjectURL(url); toast.success("Structured data exported"); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not export ledger data."); }
  }

  return <>
    <PageHeading title="Settings" description="Manage household access, sign-in methods, recovery, and structured data." />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,.8fr)]">
      <div className="space-y-4">
        <Card><CardHeader><div className="flex items-center gap-3"><Avatar><AvatarFallback>{initials(auth?.user?.display_name)}</AvatarFallback></Avatar><div className="min-w-0"><CardTitle className="text-base">{auth?.user?.display_name}</CardTitle><CardDescription>{auth?.user?.email} · {auth?.user?.role === "admin" ? "Administrator" : "Member"}</CardDescription></div></div></CardHeader>
          {auth?.auth_required && <CardContent className="border-t pt-5"><h3 className="font-medium">Change password</h3><p className="mt-1 text-sm text-muted-foreground">Choose at least 12 characters. Changing your password signs out active sessions.</p><form onSubmit={(event) => void changePassword(event)} className="mt-4 grid gap-3 sm:grid-cols-2"><div className="space-y-2 sm:col-span-2"><Label>Current password</Label><Input type="password" autoComplete="current-password" required value={passwords.current_password} onChange={(event) => setPasswords({ ...passwords, current_password: event.target.value })} /></div><div className="space-y-2"><Label>New password</Label><Input type="password" autoComplete="new-password" minLength={12} required value={passwords.new_password} onChange={(event) => setPasswords({ ...passwords, new_password: event.target.value })} /></div><div className="space-y-2"><Label>Confirm new password</Label><Input type="password" autoComplete="new-password" minLength={12} required value={passwords.confirm_password} onChange={(event) => setPasswords({ ...passwords, confirm_password: event.target.value })} /></div><div className="sm:col-span-2"><Button disabled={passwordBusy}>{passwordBusy && <LoaderCircle className="animate-spin" />}Update password</Button></div></form></CardContent>}
        </Card>
        {auth?.auth_required && <Card><CardHeader><div className="flex items-center justify-between gap-4"><div><CardTitle className="flex items-center gap-2 text-base"><KeyRound className="size-4" /> Passkeys</CardTitle><CardDescription className="mt-1">Use Face ID, Touch ID, or your device’s screen lock. Choose iCloud Keychain on Apple devices to sync a passkey.</CardDescription></div><Badge variant="outline">{passkeys.length} / 10</Badge></div></CardHeader><CardContent className="space-y-4">
          {!passkeyAvailable && <Alert variant="warning"><AlertDescription>This browser doesn’t support passkey registration. Try Safari or a recent Chrome browser on an HTTPS site.</AlertDescription></Alert>}
          <div className="flex flex-col gap-2 sm:flex-row"><Input className="max-w-sm" value={passkeyName} maxLength={60} onChange={(event) => setPasskeyName(event.target.value)} aria-label="New passkey name" /><Button onClick={() => void addPasskey()} disabled={passkeyBusy || passkeys.length >= 10}>{passkeyBusy ? <LoaderCircle className="animate-spin" /> : <Plus />} Add passkey</Button></div>
          {passkeysLoading ? <p className="py-4 text-sm text-muted-foreground">Loading passkeys…</p> : passkeys.length ? <div className="divide-y rounded-lg border">{passkeys.map((passkey) => <PasskeyRow key={passkey.id} passkey={passkey} onRename={renamePasskey} onRemove={() => setRemovePasskeyTarget({ id: passkey.id, nickname: passkey.nickname })} />)}</div> : <div className="rounded-lg border border-dashed p-5 text-center"><KeyRound className="mx-auto size-5 text-muted-foreground" /><p className="mt-2 text-sm font-medium">No passkeys on this account</p><p className="mt-1 text-xs text-muted-foreground">Add a passkey for faster sign-in on your trusted devices.</p></div>}
        </CardContent></Card>}
        {isAdmin && auth?.auth_required && <Card><CardHeader><div className="flex items-center justify-between gap-3"><div><CardTitle className="flex items-center gap-2 text-base"><Users className="size-4" /> Household access</CardTitle><CardDescription className="mt-1">Add or manage the two household accounts.</CardDescription></div><Button size="sm" onClick={() => setNewUserOpen(true)}><Plus /> Add user</Button></div></CardHeader><CardContent className="space-y-3">
          {adminUsers.map((user) => <UserRow key={user.id} user={user} isCurrent={user.id === auth.user?.id} onChange={updateUser} onReset={setResetUser} />)}
        </CardContent></Card>}
      </div>
      <div className="space-y-4">
        <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><Shield className="size-4" /> Data and privacy</CardTitle><CardDescription>Statements are kept as source PDFs. Analytics use structured transaction records.</CardDescription></CardHeader><CardContent className="space-y-4"><div className="rounded-lg bg-muted/50 p-3 text-sm"><p className="font-medium">Structured transaction history</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">Export contains transaction lines and the merchant directory. The statement PDF remains available on its statement record.</p></div><Button variant="outline" className="w-full justify-start" onClick={() => void exportData()}><FileDown /> Export structured data <Download className="ml-auto size-4" /></Button></CardContent></Card>
        {isAdmin && <Card><CardHeader><CardTitle className="text-base">Encrypted backups</CardTitle><CardDescription>Recover the household ledger from an encrypted backup file.</CardDescription></CardHeader><CardContent className="space-y-4">{backupMeta.configured ? <><div className="rounded-lg border p-3 text-sm"><p className="font-medium">{backupMeta.latest ? "Latest backup · " + new Date(backupMeta.latest.created_at).toLocaleString() : "No backup yet"}</p><p className="mt-1 text-xs text-muted-foreground">Automatic schedule · keep {backupMeta.retention_count || 30} copies</p></div><Button className="w-full" onClick={() => void createBackup()} disabled={backupBusy}>{backupBusy ? <LoaderCircle className="animate-spin" /> : <RefreshCw />} Create backup now</Button>{backupMeta.backups.map((backup) => <div key={backup.name} className="flex items-center justify-between gap-3 border-t pt-3 text-xs"><span className="truncate">{new Date(backup.created_at).toLocaleString()} · {(backup.size_bytes / 1048576).toFixed(1)} MB</span><Button variant="ghost" size="sm" asChild><a href={"/api/admin/backups/" + encodeURIComponent(backup.name)}><Download className="mr-1 size-3" /> Download</a></Button></div>)}</> : <Alert variant="warning"><AlertDescription>Encrypted backups are not configured on this server.</AlertDescription></Alert>}</CardContent></Card>}
      </div>
    </div>
    <Dialog open={newUserOpen} onOpenChange={setNewUserOpen}><DialogContent className="max-w-md"><DialogHeader><DialogTitle>Add household user</DialogTitle><DialogDescription>Create a sign-in account for your household.</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={(event) => void createUser(event)}><div className="space-y-2"><Label>Name</Label><Input required maxLength={80} value={newUser.display_name} onChange={(e) => setNewUser({ ...newUser, display_name: e.target.value })} /></div><div className="space-y-2"><Label>Email</Label><Input type="email" required value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} /></div><div className="space-y-2"><Label>Temporary password</Label><Input type="password" minLength={12} required value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} /><p className="text-xs text-muted-foreground">Use 12 characters or more and share it privately.</p></div><div className="space-y-2"><Label>Role</Label><Select value={newUser.role} onValueChange={(value) => setNewUser({ ...newUser, role: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="user">Member</SelectItem><SelectItem value="admin">Administrator</SelectItem></SelectContent></Select></div><DialogFooter><Button type="button" variant="outline" onClick={() => setNewUserOpen(false)}>Cancel</Button><Button disabled={createUserBusy}>{createUserBusy && <LoaderCircle className="animate-spin" />}Create account</Button></DialogFooter></form></DialogContent></Dialog>
    <Dialog open={!!resetUser} onOpenChange={(open) => !open && setResetUser(null)}><DialogContent className="max-w-md"><DialogHeader><DialogTitle>Reset password</DialogTitle><DialogDescription>Set a temporary password for {resetUser?.email}. Existing sessions will be signed out.</DialogDescription></DialogHeader><form onSubmit={(event) => void saveReset(event)} className="space-y-4"><div className="space-y-2"><Label>New temporary password</Label><Input type="password" minLength={12} required autoComplete="new-password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} /></div><DialogFooter><Button type="button" variant="outline" onClick={() => setResetUser(null)}>Cancel</Button><Button disabled={resetBusy}>{resetBusy && <LoaderCircle className="animate-spin" />}Reset password</Button></DialogFooter></form></DialogContent></Dialog>
    <AlertDialog open={!!removePasskeyTarget} onOpenChange={(open) => !open && setRemovePasskeyTarget(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Remove this passkey?</AlertDialogTitle><AlertDialogDescription>“{removePasskeyTarget?.nickname}” will no longer sign in to this account. You can add it again later from this device.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel disabled={passkeyBusy}>Cancel</AlertDialogCancel><AlertDialogAction disabled={passkeyBusy} onClick={(event) => { event.preventDefault(); void removePasskey(); }}>{passkeyBusy ? <LoaderCircle className="animate-spin" /> : <Trash2 />}Remove passkey</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </>;
}

function PasskeyRow({ passkey, onRename, onRemove }: { passkey: { id: string; nickname: string; created_at: string; last_used_at?: string | null; backed_up: number; device_type: string; transports: string[] }; onRename: (id: string, name: string) => void; onRemove: () => void }) {
  const [name, setName] = React.useState(passkey.nickname || "Passkey");
  return <div className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center"><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted"><KeyRound className="size-4" /></span><div className="min-w-0 flex-1"><Input className="h-8 max-w-xs" value={name} maxLength={60} onChange={(event) => setName(event.target.value)} aria-label="Passkey name" /><p className="mt-1 text-xs text-muted-foreground">Added {new Date(passkey.created_at).toLocaleDateString()} · {passkey.backed_up ? "Synced by authenticator" : "Device stored"}{passkey.last_used_at ? " · Used " + new Date(passkey.last_used_at).toLocaleDateString() : " · Not used yet"}</p>{passkey.transports.length > 0 && <p className="text-[10px] text-muted-foreground">{passkey.transports.join(" · ")}</p>}</div><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => void onRename(passkey.id, name)}>Save name</Button><Button size="icon" variant="ghost" onClick={onRemove} aria-label="Remove passkey"><Trash2 /></Button></div></div>;
}

function UserRow({ user, isCurrent, onChange, onReset }: { user: User; isCurrent: boolean; onChange: (user: User, change: Partial<User>) => void; onReset: (user: User) => void }) {
  const [name, setName] = React.useState(user.display_name);
  const [role, setRole] = React.useState(user.role);
  const [active, setActive] = React.useState(!!user.active);
  React.useEffect(() => { setName(user.display_name); setRole(user.role); setActive(!!user.active); }, [user]);
  const changed = name !== user.display_name || role !== user.role || active !== !!user.active;
  return <div className="flex flex-col gap-3 rounded-lg border p-3 lg:flex-row lg:items-center"><Avatar className="size-9"><AvatarFallback>{initials(name)}</AvatarFallback></Avatar><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><p className="truncate text-sm font-medium">{name}{isCurrent ? " · You" : ""}</p><Badge variant={user.active ? "success" : "secondary"}>{user.active ? "Active" : "Inactive"}</Badge></div><p className="truncate text-xs text-muted-foreground">{user.email}</p><div className="mt-2 flex flex-wrap items-center gap-2"><Input className="h-8 w-36" value={name} onChange={(event) => setName(event.target.value)} aria-label="User display name" /><Select value={role} disabled={isCurrent} onValueChange={(value) => setRole(value as User["role"])}><SelectTrigger className="h-8 w-36"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="user">Member</SelectItem><SelectItem value="admin">Administrator</SelectItem></SelectContent></Select><div className="flex items-center gap-2 text-xs text-muted-foreground"><Switch checked={active} onCheckedChange={setActive} disabled={isCurrent} aria-label="Active account" />{active ? "Access on" : "Access off"}</div></div></div><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => onReset(user)}>Reset password</Button><Button size="sm" onClick={() => onChange(user, { display_name: name, role, active })} disabled={!changed}>Save</Button></div></div>;
}
