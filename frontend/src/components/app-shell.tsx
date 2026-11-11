import * as React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowLeftRight,
  ChevronDown,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  ShieldCheck,
  Store,
  Sun,
} from "lucide-react";
import { toast } from "sonner";
import { useLedger } from "@/lib/ledger";
import { initials } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Spotlight } from "@/components/spotlight";

const navItems = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/transactions", label: "Transactions", icon: ArrowLeftRight, end: false },
  { to: "/statements", label: "Statements", icon: FileText, end: false },
  { to: "/merchants", label: "Merchants", icon: Store, end: false },
  { to: "/settings", label: "Settings", icon: Settings, end: false },
];

function pageName(pathname: string) {
  const match = navItems.find((item) => item.to === pathname || (item.to !== "/" && pathname.startsWith(item.to)));
  return match?.label || "Overview";
}

function Navigation({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const { auth, transactions } = useLedger();
  const reviewCount = transactions.filter((item) => item.allocation === "Needs review" || item.ocr_amount_match === 0).length;
  return (
    <>
      <div className="flex h-[68px] items-center gap-3 px-4">
        <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground">
          <span className="text-lg font-bold tracking-tight">h</span>
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="font-semibold tracking-tight">homeledger</div>
            <div className="text-[10px] font-medium uppercase tracking-[0.17em] text-muted-foreground">Household finance</div>
          </div>
        )}
      </div>
      {!collapsed && (
        <div className="mx-3 mb-6 flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5">
          <Avatar className="size-8 rounded-lg">
            <AvatarFallback className="rounded-lg bg-muted">{initials(auth?.user?.display_name)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">Shiv’s household</div>
            <div className="truncate text-xs text-muted-foreground">Private workspace</div>
          </div>
          <ChevronDown className="size-4 text-muted-foreground" />
        </div>
      )}
      {!collapsed && <div className="mb-2 px-6 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Workspace</div>}
      <nav aria-label="Main navigation" className="grid gap-1 px-2">
        {navItems.slice(0, 4).map((item) => {
          const Icon = item.icon;
          const link = (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                "group relative flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors " +
                (isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/70 hover:text-foreground") +
                (collapsed ? " justify-center px-0" : "")
              }
              title={collapsed ? item.label : undefined}
            >
              <Icon className="size-[18px] shrink-0" strokeWidth={1.8} />
              {!collapsed && <span className="flex-1">{item.label}</span>}
              {!collapsed && item.to === "/transactions" && reviewCount > 0 && (
                <Badge variant="secondary" className="h-5 min-w-5 justify-center px-1.5 text-[10px] tabular">{reviewCount}</Badge>
              )}
            </NavLink>
          );
          if (!collapsed) return link;
          return (
            <Tooltip key={item.to}>
              <TooltipTrigger asChild>{link}</TooltipTrigger>
              <TooltipContent side="right">{item.label}{item.to === "/transactions" && reviewCount ? " · " + reviewCount + " to review" : ""}</TooltipContent>
            </Tooltip>
          );
        })}
      </nav>
      {!collapsed && <div className="mb-2 mt-8 px-6 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Your setup</div>}
      <nav aria-label="Settings" className="grid gap-1 px-2">
        {(() => {
          const item = navItems[4];
          const Icon = item.icon;
          const link = (
            <NavLink
              to={item.to}
              onClick={onNavigate}
              className={({ isActive }) =>
                "flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors " +
                (isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/70 hover:text-foreground") +
                (collapsed ? " justify-center px-0" : "")
              }
              title={collapsed ? item.label : undefined}
            >
              <Icon className="size-[18px] shrink-0" strokeWidth={1.8} />
              {!collapsed && item.label}
            </NavLink>
          );
          return collapsed ? (
            <Tooltip key={item.to}>
              <TooltipTrigger asChild>{link}</TooltipTrigger>
              <TooltipContent side="right">{item.label}</TooltipContent>
            </Tooltip>
          ) : link;
        })()}
      </nav>
      <div className="mt-auto p-3">
        <div className={"flex items-center gap-3 rounded-lg border bg-card px-3 py-3 " + (collapsed ? "justify-center px-0" : "")}>
          <ShieldCheck className="size-4 shrink-0 text-muted-foreground" />
          {!collapsed && (
            <div className="min-w-0">
              <div className="text-xs font-medium">Household access</div>
              <div className="text-[11px] text-muted-foreground">Sign-in protected</div>
            </div>
          )}
          {!collapsed && <span className="ml-auto size-2 rounded-full bg-emerald-500" />}
        </div>
      </div>
    </>
  );
}

export function AppShell() {
  const { auth, api } = useLedger();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = React.useState(() => {
    try { return localStorage.getItem("household-ledger-sidebar") === "collapsed"; } catch { return false; }
  });
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [theme, setTheme] = React.useState(document.documentElement.dataset.theme || "light");

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function toggleSidebar() {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem("household-ledger-sidebar", next ? "collapsed" : "expanded"); } catch {}
  }

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    document.documentElement.classList.toggle("dark", next === "dark");
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", next === "dark" ? "#09090b" : "#ffffff");
    try { localStorage.setItem("household-ledger-theme", next); } catch {}
    setTheme(next);
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST", body: JSON.stringify({}) });
      window.location.assign("/login");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not sign out.");
    }
  }

  return (
    <TooltipProvider delayDuration={250}>
      <div className="min-h-svh bg-background">
        <aside className={"fixed inset-y-0 left-0 z-30 hidden border-r bg-background transition-[width] duration-200 md:flex md:flex-col " + (collapsed ? "w-[68px]" : "w-64")}>
          <Navigation collapsed={collapsed} />
          <div className="px-3 pb-3">
            <Button variant="ghost" className={"w-full text-muted-foreground " + (collapsed ? "px-0" : "justify-start")} onClick={toggleSidebar} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}>
              {collapsed ? <PanelLeftOpen /> : <><PanelLeftClose /><span>Collapse navigation</span></>}
            </Button>
          </div>
        </aside>

        <div className={"min-h-svh transition-[padding] duration-200 " + (collapsed ? "md:pl-[68px]" : "md:pl-64")}>
          <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
                <SheetTrigger asChild>
                  <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation"><Menu /></Button>
                </SheetTrigger>
                <SheetContent side="left" className="flex w-[280px] flex-col p-0">
                  <SheetTitle className="sr-only">Household navigation</SheetTitle>
                  <Navigation onNavigate={() => setMobileOpen(false)} />
                </SheetContent>
              </Sheet>
              <div className="truncate text-sm text-muted-foreground">
                Household <span className="px-1.5 text-border">/</span><span className="font-medium text-foreground">{pageName(location.pathname)}</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <Button variant="outline" size="sm" className="hidden gap-2 text-muted-foreground sm:flex" onClick={() => setSearchOpen(true)}>
                <Search className="size-4" /><span>Search</span><kbd className="ml-1 rounded border bg-muted px-1.5 py-0.5 text-[10px]">⌘K</kbd>
              </Button>
              <Button variant="ghost" size="icon" className="sm:hidden" onClick={() => setSearchOpen(true)} aria-label="Search"><Search /></Button>
              <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
                {theme === "dark" ? <Sun /> : <Moon />}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" className="ml-1 size-9 rounded-full p-0" aria-label="Account menu">
                    <Avatar className="size-8"><AvatarFallback>{initials(auth?.user?.display_name)}</AvatarFallback></Avatar>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <div className="px-2 py-1.5">
                    <p className="text-sm font-medium">{auth?.user?.display_name}</p>
                    <p className="truncate text-xs text-muted-foreground">{auth?.user?.email}</p>
                  </div>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => navigate("/settings")}><Settings className="mr-2 size-4" />Settings</DropdownMenuItem>
                  {auth?.auth_required && <DropdownMenuItem onSelect={() => void logout()}><LogOut className="mr-2 size-4" />Sign out</DropdownMenuItem>}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </header>
          <main className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 sm:py-8 lg:px-10">
            <Outlet />
          </main>
        </div>
        <Spotlight open={searchOpen} onOpenChange={setSearchOpen} />
      </div>
    </TooltipProvider>
  );
}
