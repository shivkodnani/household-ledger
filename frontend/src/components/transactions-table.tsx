import { Eye, PencilLine } from "lucide-react";
import type { Transaction } from "@/lib/types";
import { initials, money, shortDate } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

function allocationBadge(allocation: string) {
  if (allocation === "Needs review") return <Badge variant="warning">Needs review</Badge>;
  if (allocation === "Shared") return <Badge variant="info">Shared · 50%</Badge>;
  if (allocation === "Wife personal") return <Badge variant="secondary">Wife · 100%</Badge>;
  if (allocation === "Your personal") return <Badge variant="outline">Yours · 0%</Badge>;
  if (allocation === "Card payment") return <Badge variant="secondary">Card payment</Badge>;
  return <Badge variant="outline">{allocation}</Badge>;
}

export function TransactionsTable({
  items,
  onEdit,
  onSnapshot,
  showActions = true,
  emptyTitle = "No transactions found",
  emptyText = "Try changing your filters or add a manual transaction.",
}: {
  items: Transaction[];
  onEdit?: (item: Transaction) => void;
  onSnapshot?: (item: Transaction) => void;
  showActions?: boolean;
  emptyTitle?: string;
  emptyText?: string;
}) {
  if (!items.length) {
    return (
      <div className="grid min-h-48 place-items-center px-6 py-10 text-center">
        <div>
          <p className="font-medium">{emptyTitle}</p>
          <p className="mt-1 text-sm text-muted-foreground">{emptyText}</p>
        </div>
      </div>
    );
  }
  return (
    <Table className="min-w-[920px]">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="min-w-[230px]">Merchant / description</TableHead>
          <TableHead>Date</TableHead>
          <TableHead>Made by</TableHead>
          <TableHead>Allocation</TableHead>
          <TableHead className="text-right">Amount</TableHead>
          <TableHead className="text-right">Wife owes</TableHead>
          {showActions && <TableHead className="w-24" />}
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.id} className="group">
            <TableCell>
              <div className="flex min-w-0 items-center gap-2.5">
                <Avatar className="size-8 rounded-lg">
                  <AvatarFallback className="rounded-lg bg-muted text-xs">{initials(item.merchant || item.description)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <p className="truncate font-medium">{item.merchant || item.description}</p>
                  <p className="max-w-[280px] truncate text-xs text-muted-foreground">{item.description}{item.payment_method ? " · " + item.payment_method : ""}</p>
                </div>
              </div>
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">{shortDate(item.date)}</TableCell>
            <TableCell className="text-muted-foreground">{item.person === "Unknown" ? "—" : item.person}</TableCell>
            <TableCell>{allocationBadge(item.allocation)}</TableCell>
            <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">{money(item.amount_inr)}</TableCell>
            <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">{money(item.owed_inr)}</TableCell>
            {showActions && (
              <TableCell>
                <div className="flex items-center justify-end gap-1 opacity-75 transition-opacity group-hover:opacity-100">
                  {onSnapshot && item.statement_id && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="ghost" size="icon" className="size-8" onClick={() => onSnapshot(item)} aria-label="View statement line snapshot">
                          <Eye className="size-4" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>View source line</TooltipContent>
                    </Tooltip>
                  )}
                  {onEdit && (
                    <Button variant="ghost" size="icon" className="size-8" onClick={() => onEdit(item)} aria-label="Edit transaction">
                      <PencilLine className="size-4" />
                    </Button>
                  )}
                </div>
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
