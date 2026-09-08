/**
 * Overview — the corpus family-tile table (`specs/loupe-ui-design.md`, Overview).
 *
 * One row per loaded contract × held grain, over the **full held window** — no date filter,
 * matching the absent sidebar pickers. HTTP only: one `GET /v1/dq/checks` per row. This module
 * does not group `findings[]` and does not compute a count.
 *
 * Cells carry the headline `count unit` and nothing else. Family *detail* stays on Review; a
 * Glide probe found newlines do not render in the cell, and a detail line that silently
 * collapses is worse than no detail (`plans/15-overview-headlines.md`).
 *
 * The by-root bar chart, the "noise first" sort and the sessions / records / hit Stats from the
 * canvas are **out of scope**: those were demo-cull research, not this page.
 */

import { useMemo, useState } from "react";
import type { FamilyCard, Frequency } from "../api/types";
import { FAMILY_LABEL, FAMILY_ORDER } from "../api/types";
import type { Column } from "../components/primitives";
import {
  Badge,
  Callout,
  Caption,
  Pill,
  Row,
  RowAction,
  Stack,
  Table,
  Text,
} from "../components/primitives";
import { formatCount } from "../charts/scale";
import * as help from "../help";

export interface OverviewRow {
  contract_id: string;
  root: string | null;
  exchange: string | null;
  dual: boolean;
  frequency: Frequency;
  /** Null when the row could not be read at all; false when no run has completed. */
  checked: boolean | null;
  families: Record<string, FamilyCard>;
  error?: string | null;
}

type GrainFilter = "All" | "Daily" | "Minute";

const FILTERS: GrainFilter[] = ["All", "Daily", "Minute"];

/**
 * The headline for one family cell.
 *
 * `checked: false` says the check has not run rather than painting a zero as clean — a zero is
 * only a real answer once a run has completed.
 */
export function familyCell(row: OverviewRow, family: string): string {
  if (row.error) return row.error;
  if (row.checked === false) return "Check has not run";
  const card = row.families[family];
  return `${formatCount(card?.count ?? 0)} ${card?.unit ?? ""}`.trim();
}

export function Overview({
  rows,
  onOpen,
}: {
  rows: OverviewRow[];
  onOpen: (contract: string, frequency: Frequency) => void;
}) {
  const [grain, setGrain] = useState<GrainFilter>("All");

  const visible = useMemo(
    () =>
      rows.filter((row) =>
        grain === "All" ? true : row.frequency === (grain.toLowerCase() as Frequency),
      ),
    [rows, grain],
  );

  if (rows.length === 0) {
    return (
      <Callout tone="info">
        No contracts loaded yet. Load demo data from the sidebar to see quality for it.
      </Callout>
    );
  }

  const columns: Column<OverviewRow>[] = [
    {
      key: "contract",
      header: "Contract",
      width: 150,
      // Stacked cell from the tiles canvas: the id leads, provenance is tertiary context.
      // It is also the row's control, so the selection is reachable without a pointer.
      render: (row) => (
        <RowAction
          label={`Open ${row.contract_id} ${row.frequency} in Review`}
          onClick={() => onOpen(row.contract_id, row.frequency)}
        >
          <Stack gap={1}>
            <Text weight="semibold">{row.contract_id}</Text>
            <Text size="small" tone="tertiary">
              {[row.root, row.exchange].filter(Boolean).join(" · ")}
              {row.dual ? " · dual grain" : ""}
            </Text>
          </Stack>
        </RowAction>
      ),
    },
    {
      key: "grain",
      header: "Grain",
      width: 80,
      render: (row) => <Badge>{row.frequency === "minute" ? "Minute" : "Daily"}</Badge>,
    },
    ...FAMILY_ORDER.map((family) => ({
      key: family,
      header: FAMILY_LABEL[family],
      help: help.CARDS[family],
      render: (row: OverviewRow) => {
        const live = (row.families[family]?.count ?? 0) > 0 && !row.error;
        return (
          <Text tone={live ? "primary" : "tertiary"} weight={live ? "semibold" : "normal"}>
            {familyCell(row, family)}
          </Text>
        );
      },
    })),
  ];

  return (
    <Stack gap={10}>
      <Row gap={8} wrap role="group" aria-label="Grain">
        <Text size="small" tone="secondary">
          Grain
        </Text>
        {FILTERS.map((filter) => (
          <Pill key={filter} active={grain === filter} onClick={() => setGrain(filter)}>
            {filter}
          </Pill>
        ))}
      </Row>

      {visible.length === 0 ? (
        <Caption>{`No ${grain.toLowerCase()} rows in the loaded set.`}</Caption>
      ) : (
        <Table
          columns={columns}
          rows={visible}
          rowKey={(row) => `${row.contract_id}-${row.frequency}`}
          onSelect={(row) => onOpen(row.contract_id, row.frequency)}
        />
      )}
    </Stack>
  );
}
