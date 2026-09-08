/**
 * Page state, in one place, so the two destinations agree on what "selected" means.
 *
 * There is no router. Overview | Review is a sidebar segmented control, not a URL — it was
 * never a persona selector and it is not a third page (`specs/loupe-ui-design.md`,
 * Navigation). Deep links are not a v1 surface.
 *
 * The one rule with teeth: **Overview click-through sets contract and quality grain and
 * leaves family alone.** Family is whatever Review last had, defaulting to gaps.
 */

import { useCallback, useMemo, useState } from "react";
import type { Contract, Family, Frequency } from "./api/types";

export type Destination = "Overview" | "Review";

export interface AppState {
  destination: Destination;
  contract: string | null;
  frequency: Frequency | null;
  family: Family;
  start: string | null;
  end: string | null;
}

export interface AppActions {
  setDestination: (destination: Destination) => void;
  setContract: (contract: string | null) => void;
  setFrequency: (frequency: Frequency) => void;
  setFamily: (family: Family) => void;
  setStart: (start: string | null) => void;
  setEnd: (end: string | null) => void;
  /** Overview row click: open Review on that contract × grain, family untouched. */
  openInReview: (contract: string, frequency: Frequency) => void;
}

/** Grains a contract actually holds, minute first — the order the picker offers. */
export function heldGrains(contract: Contract | undefined): Frequency[] {
  const held = new Set(contract?.frequencies_available ?? []);
  return (["minute", "daily"] as Frequency[]).filter((grain) => held.has(grain));
}

/**
 * Resolve the quality grain for a contract.
 *
 * The current selection persists when the contract changes **if that grain is available**;
 * otherwise it resolves to Minute when available, then Daily. A single-grain contract has no
 * choice at all (`specs/loupe-ui-design.md`, Sidebar).
 */
export function resolveFrequency(
  available: Frequency[],
  current: Frequency | null,
): Frequency | null {
  if (current && available.includes(current)) return current;
  if (available.includes("minute")) return "minute";
  return available[0] ?? null;
}

export function useAppState(initial?: Partial<AppState>): AppState & AppActions {
  const [destination, setDestination] = useState<Destination>(
    initial?.destination ?? "Overview",
  );
  const [contract, setContract] = useState<string | null>(initial?.contract ?? null);
  const [frequency, setFrequency] = useState<Frequency | null>(initial?.frequency ?? null);
  const [family, setFamily] = useState<Family>(initial?.family ?? "gaps");
  const [start, setStart] = useState<string | null>(initial?.start ?? null);
  const [end, setEnd] = useState<string | null>(initial?.end ?? null);

  const openInReview = useCallback((next: string, grain: Frequency) => {
    setContract(next);
    setFrequency(grain);
    setDestination("Review");
  }, []);

  return useMemo(
    () => ({
      destination,
      contract,
      frequency,
      family,
      start,
      end,
      setDestination,
      setContract,
      setFrequency,
      setFamily,
      setStart,
      setEnd,
      openInReview,
    }),
    [destination, contract, frequency, family, start, end, openInReview],
  );
}

// ---------------------------------------------------------------------- header captions

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** `2026-02` → `February 2026`. Null when the metadata is unavailable — never invented. */
export function contractMonthCaption(value: string | null | undefined): string | null {
  if (!value) return null;
  const [year, month] = value.split("-");
  const index = Number(month) - 1;
  if (!year || Number.isNaN(index) || index < 0 || index > 11) return null;
  return `${MONTHS[index]} ${year}`;
}

/** `2025-12-19` → `Dec 19, 2025`. */
export function humanDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/**
 * The Review header: contract, month, exchange, observed coverage for the resolved grain,
 * the grain itself, then the independently filtered window.
 *
 * Coverage is the **observed** range, not a listing or expiry claim. Omit a segment whose
 * metadata is unavailable rather than inventing it.
 */
export function reviewHeaderParts(
  contractId: string,
  metadata: Contract | undefined,
  frequency: Frequency | null,
  start: string | null,
  end: string | null,
): string[] {
  const parts = [contractId];
  const month = contractMonthCaption(metadata?.contract_month);
  if (month) parts.push(month);
  const exchange = (metadata?.exchange ?? "").trim();
  if (exchange) parts.push(exchange);

  if (frequency) {
    const coverage = metadata?.coverage?.[frequency];
    const first = humanDate(coverage?.first_trade_date);
    const last = humanDate(coverage?.last_trade_date);
    const grain = frequency === "minute" ? "Minute" : "Daily";
    if (first && last) parts.push(`${grain} coverage: ${first} – ${last}`);
    parts.push(`${grain} quality grain`);
  }

  const window = windowCaption(start, end);
  if (window) parts.push(window);
  return parts;
}

export function windowCaption(start: string | null, end: string | null): string {
  const from = humanDate(start);
  const to = humanDate(end);
  if (from && to) return from === to ? `Review window: ${from}` : `Review window: ${from} – ${to}`;
  if (from) return `Review window: from ${from}`;
  if (to) return `Review window: through ${to}`;
  return "";
}
