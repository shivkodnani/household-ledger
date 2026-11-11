import * as React from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Eye, EyeOff, KeyRound, LoaderCircle, Moon, ShieldCheck, Sun } from "lucide-react";
import { useLedger } from "@/lib/ledger";
import { credentialPayload, requestOptionsFromJSON } from "@/lib/passkeys";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";

export function LoginPage() {
  const { api, reload } = useLedger();
  const navigate = useNavigate();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [passkeyBusy, setPasskeyBusy] = React.useState(false);
  const [theme, setTheme] = React.useState(document.documentElement.dataset.theme || "light");
  const canUsePasskeys = typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials?.get;

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    document.documentElement.classList.toggle("dark", next === "dark");
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", next === "dark" ? "#09090b" : "#ffffff");
    try { localStorage.setItem("household-ledger-theme", next); } catch {}
    setTheme(next);
  }

  async function finishLogin() {
    await reload();
    navigate("/", { replace: true });
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      await finishLogin();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-in failed. Please try again.");
      setBusy(false);
    }
  }

  async function signInWithPasskey() {
    setPasskeyBusy(true);
    setError("");
    try {
      const options = await api<{ challenge_id: string; public_key: PublicKeyCredentialRequestOptions }>("/api/auth/passkey/login/options", {
        method: "POST",
        body: JSON.stringify({}),
      });
      const credential = await navigator.credentials.get({ publicKey: requestOptionsFromJSON(options.public_key) });
      if (!credential || !(credential instanceof PublicKeyCredential)) throw new Error("Passkey sign-in was cancelled.");
      await api("/api/auth/passkey/login/verify", {
        method: "POST",
        body: JSON.stringify({ challenge_id: options.challenge_id, credential: credentialPayload(credential, false) }),
      });
      await finishLogin();
    } catch (reason) {
      setError(reason instanceof DOMException && reason.name === "NotAllowedError"
        ? "Passkey sign-in was cancelled or timed out. Try again or use your password."
        : reason instanceof Error ? reason.message : "Passkey sign-in failed. Use your password or try again.");
      setPasskeyBusy(false);
      setBusy(false);
    }
  }

  return (
    <main className="relative grid min-h-svh place-items-center overflow-hidden bg-muted/30 px-4 py-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,hsl(var(--muted))_0%,transparent_60%)] opacity-60" />
      <Button variant="outline" size="icon" className="absolute right-5 top-5 z-10" onClick={toggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
        {theme === "dark" ? <Sun /> : <Moon />}
      </Button>
      <Card className="relative w-full max-w-[420px] shadow-lg shadow-black/5">
        <CardHeader className="items-center space-y-3 pb-5 pt-8 text-center">
          <div className="grid size-12 place-items-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
            <span className="text-2xl font-bold">h</span>
          </div>
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.17em] text-muted-foreground">Private household workspace</p>
            <CardTitle className="text-2xl tracking-tight">Welcome back</CardTitle>
            <CardDescription className="mt-2">Sign in to review your household spending.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-5 px-6 pb-7 sm:px-8">
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email address</Label>
              <Input id="email" type="email" autoComplete="username" required autoFocus value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
              </div>
              <div className="relative">
                <Input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className="pr-11" />
                <Button type="button" variant="ghost" size="icon" className="absolute right-1 top-1 h-7 w-8 text-muted-foreground" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>
                  {showPassword ? <EyeOff /> : <Eye />}
                </Button>
              </div>
            </div>
            <Button className="w-full" type="submit" disabled={busy || passkeyBusy}>
              {busy ? <LoaderCircle className="animate-spin" /> : <>Sign in <ArrowRight /></>}
            </Button>
          </form>
          {canUsePasskeys && (
            <>
              <div className="relative py-1">
                <Separator />
                <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-card px-2 text-xs text-muted-foreground">or continue with</span>
              </div>
              <Button variant="outline" className="w-full" onClick={() => void signInWithPasskey()} disabled={busy || passkeyBusy}>
                {passkeyBusy ? <LoaderCircle className="animate-spin" /> : <KeyRound />}
                {passkeyBusy ? "Checking your passkey…" : "Sign in with a passkey"}
              </Button>
              <p className="flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
                <ShieldCheck className="size-3.5" /> Use Face ID, Touch ID, or your device’s screen lock.
              </p>
            </>
          )}
          <p className="pt-1 text-center text-xs leading-relaxed text-muted-foreground">
            Your statements and transaction history stay inside your private household ledger.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
