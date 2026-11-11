import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const money = (value: number | string | null | undefined) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value || 0));

export const shortDate = (value?: string | null) =>
  value
    ? new Date(value + "T00:00:00").toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    : "—";

export const initials = (value?: string | null) =>
  (value || "?").trim().slice(0, 1).toUpperCase();

export const monthLabel = (value: string) =>
  new Date(value + "-01T00:00:00").toLocaleDateString("en-IN", {
    month: "long",
    year: "numeric",
  });

export function shareForAllocation(allocation: string, custom = 0) {
  if (allocation === "Shared") return 50;
  if (allocation === "Wife personal") return 100;
  if (allocation === "Custom") return custom;
  return 0;
}
