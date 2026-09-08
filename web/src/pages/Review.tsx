/**
 * The reviewer main column: cards, Daily OHLCV, VWAP, picture, aggregated issues.
 *
 * That order is load-bearing (`specs/loupe-ui-design.md`, Main column). HTTP only: family
 * membership, overlay marks and What-we-did come from `GET /v1/dq/checks`. This module does
 * not group `findings[]` and computes no quality or insight maths — the four cards *are* the
 * family control, there is no Check row and no score caption.
 *
 * Report-only: no apply, override, dismiss, accept, resolve or edit control anywhere below.
 */

import type {
  AggregatedIssue,
  Bar,
  ChecksResponse,
  Family,
  FamilyCard,
  Picture,
  VwapPoint,
} from "../api/types";
import { FAMILY_LABEL, FAMILY_ORDER } from "../api/types";
import { ApiProblem } from "../api/client";
import { Ohlcv } from "../charts/Ohlcv";
import { Vwap } from "../charts/Vwap";
import { GapRibbon, PatternHistogram } from "../charts/Pictures";
import { namesVwapBreaks, overlaySlots } from "../charts/overlay";
import { chartScopeKey, formatCount } from "../charts/scale";
import type { Column } from "../components/primitives";
import { Callout, Caption, Stack, Table, Text } from "../components/primitives";
import * as help from "../help";
import { theme } from "../theme/theme";

export interface ReviewProps {
  checks: ChecksResponse;
  bars: { data: Bar[]; meta: { bar_source?: string } };
  /** The envelope, or the problem the API answered with — a refusal is content. */
  vwap: { data: VwapPoint[] } | ApiProblem | null;
  family: Family;
  onSelectFamily: (family: Family) => void;
  scope: { contract: string; frequency: string | null; start: string | null; end: string | null };
}

export function Review({
  checks,
  bars,
  vwap,
  family,
  onSelectFamily,
  scope,
}: ReviewProps) {
  const overlay = checks.overlay;
  // Everything below reads *this* envelope, so it names the family the envelope was composed
  // for — not the one the reader just clicked. A card click is optimistic and the fetch takes
  // a moment; in that moment `family` is already the new one, and heading the old gaps ribbon
  // "Picture of invalid values" would be a caption that lies about the picture under it.
  const shown = (FAMILY_ORDER.find((name) => name === overlay?.family) ?? family) as Family;
  const frequency = checks.scope?.frequency ?? scope.frequency;
  const source =
    bars.meta?.bar_source ??
    (frequency === "minute" ? "derived_from_minute" : "supplied_daily");
  const sourceLabel =
    source === "derived_from_minute" ? "Derived from minute" : "Supplied daily";
  const slots = overlaySlots(bars.data ?? [], overlay?.ohlcv ?? []);

  return (
    <Stack gap={18}>
      <FamilyCards cards={checks.families ?? []} selected={family} onSelect={onSelectFamily} />

      {!checks.checked ? (
        <Callout tone="info">Validation has not finished for this contract yet.</Callout>
      ) : (
        <>
          <Stack gap={6}>
            <h2>Daily OHLCV</h2>
            <Caption>
              {`${sourceLabel} · ${grainLabel(frequency)} quality grain · selected family. ` +
                "Rule IDs stay off the candle."}
            </Caption>
            <Ohlcv
              slots={slots}
              family={shown}
              scopeKey={chartScopeKey(scope, bars.data ?? [], "trade_date")}
            />
          </Stack>

          <Stack gap={6}>
            <h2>Rolling 15-minute VWAP</h2>
            <VwapPanel
              vwap={vwap}
              overlay={overlay}
              family={shown}
              qualityFrequency={frequency}
              scope={scope}
            />
          </Stack>

          <PictureOf picture={overlay?.picture ?? {}} family={shown} />
          <Issues issues={checks.issues ?? []} family={shown} />
        </>
      )}
    </Stack>
  );
}

function grainLabel(frequency: string | null | undefined): string {
  return frequency === "minute" ? "Minute" : frequency === "daily" ? "Daily" : "";
}

/**
 * Four cards, and the cards *are* the family control.
 *
 * Type hierarchy: the count / unit line leads and is slightly larger than body; the detail
 * under it is regular body size. Not `st.metric`'s inverted hierarchy of a tiny label over a
 * huge value. Help attaches to the **count**, never to the family name.
 */
export function FamilyCards({
  cards,
  selected,
  onSelect,
}: {
  cards: FamilyCard[];
  selected: Family;
  onSelect: (family: Family) => void;
}) {
  const byId = new Map(cards.map((card) => [card.family, card]));
  return (
    <div
      role="group"
      aria-label="Check families"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12,
      }}
    >
      {FAMILY_ORDER.map((name) => {
        const card = byId.get(name);
        const label = card?.label ?? FAMILY_LABEL[name];
        const count = card?.count ?? 0;
        const unit = card?.unit ?? "";
        const detail = (card?.detail ?? "").trim();
        const active = name === selected;
        return (
          <button
            key={name}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(name)}
            style={{
              textAlign: "left",
              background: active ? theme.fill.primary : theme.bg.elevated,
              border: `1px solid ${active ? theme.stroke.focused : theme.stroke.primary}`,
              borderRadius: "var(--radius)",
              padding: 12,
              cursor: "pointer",
            }}
          >
            <div style={{ fontSize: "var(--size-small)", color: theme.text.tertiary }}>
              {label}
              {active ? " · selected" : ""}
            </div>
            <div
              title={help.CARDS[name]}
              aria-description={help.CARDS[name]}
              style={{ fontSize: "var(--size-count)", fontWeight: 600, margin: "3px 0 0" }}
            >
              {`${formatCount(count)} ${unit}`.trim()}
            </div>
            {detail ? (
              <div style={{ color: theme.text.secondary, marginTop: 4 }}>{detail}</div>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** The panel stays and explains itself; it never silently renders empty. */
export function VwapPanel({
  vwap,
  overlay,
  family,
  qualityFrequency,
  scope,
}: {
  vwap: { data: VwapPoint[] } | ApiProblem | null;
  overlay: ChecksResponse["overlay"] | undefined;
  family: Family;
  qualityFrequency: string | null | undefined;
  scope: Record<string, unknown>;
}) {
  if (vwap instanceof ApiProblem) {
    // A daily-only contract cannot serve a 15-minute VWAP, and the structured refusal *is*
    // this panel's content — not an empty chart and not a 15-day VWAP.
    if (vwap.code === "CAP.FREQUENCY_UNAVAILABLE") {
      // The refusal is the panel's content and it already says what is missing. The VWAP
      // jargon line stays with a drawn chart, where the term needs explaining; repeating
      // "needs minute bars" underneath the sentence that just said it is noise.
      return (
        <Callout tone="info" title="Needs minute bars">
          <Text size="small">{vwap.detail ?? vwap.title}</Text>
        </Callout>
      );
    }
    return <Callout tone="warning">{vwap.detail ?? vwap.title}</Callout>;
  }
  if (vwap === null) return <Caption>No VWAP points in this window.</Caption>;

  const points = vwap.data ?? [];
  // At Daily quality grain the minute tape is context, not evidence for the selected family:
  // keep the line, label it, and suppress the marks.
  const contextOnly = qualityFrequency === "daily";
  const showFamilyMarks = !contextOnly;

  return (
    <Stack gap={6}>
      {contextOnly ? <Caption>Minute tape · context only for Daily quality grain</Caption> : null}
      <Vwap
        points={points}
        family={family}
        vwapMeta={overlay?.vwap}
        showFamilyMarks={showFamilyMarks}
        nameBreaks={namesVwapBreaks(family, overlay?.vwap, showFamilyMarks)}
        scopeKey={chartScopeKey(scope, points, "ts_utc")}
      />
      <Caption>{help.JARGON.vwap}</Caption>
    </Stack>
  );
}

/** The close look at the same family as the cards and the overlay. Lives below VWAP. */
export function PictureOf({ picture, family }: { picture: Picture; family: Family }) {
  const label = FAMILY_LABEL[family];
  const kind = picture.kind ?? "empty";
  const caption = picture.caption ?? "";
  const ruleIds = picture.rule_ids ?? [];

  return (
    <Stack gap={6}>
      <h2>{`Picture of ${label.toLowerCase()}`}</h2>
      {kind === "empty" ? (
        <Caption>{caption || "This check ran. Nothing in this window."}</Caption>
      ) : (
        <>
          {caption && kind !== "absent_session" ? <Text>{caption}</Text> : null}
          {/* Rule IDs are a caption under the picture, never a headline and never a hover. */}
          {ruleIds.length ? <Caption>{ruleIds.join(" · ")}</Caption> : null}

          {kind === "gaps_ribbon" ? <GapRibbon slots={picture.slots ?? []} /> : null}

          {kind === "absent_session" ? (
            <Callout tone="info">
              {caption ||
                "Settlement never arrived. Loupe does not invent a zero-filled bar."}
            </Callout>
          ) : null}

          {kind === "duplicate_rows" ? <RecordTable rows={picture.rows ?? []} /> : null}

          {kind === "invalid_cell" ? (
            <Stack gap={6}>
              {picture.field ? (
                <Text>
                  Broken cell: <strong>{picture.field}</strong>
                </Text>
              ) : null}
              {picture.evidence_frequency || picture.evidence_source ? (
                <Caption>
                  {["Evidence", picture.evidence_frequency, picture.evidence_source]
                    .filter(Boolean)
                    .join(" · ")}
                </Caption>
              ) : null}
              {picture.bar ? <RecordTable rows={[picture.bar]} /> : null}
            </Stack>
          ) : null}

          {kind === "pattern_histogram" ? (
            <Stack gap={6}>
              <Caption>
                {`Showing ${picture.buckets_shown ?? (picture.buckets ?? []).length} of ` +
                  `${picture.patterns_total ?? picture.buckets_shown ?? 0} standing patterns`}
              </Caption>
              <PatternHistogram
                buckets={picture.buckets ?? []}
                axisLabel={picture.axis_label ?? picture.dimension ?? "Bucket"}
              />
              <Caption>
                A findings share much larger than record exposure is over-representation. The
                configured standing threshold, not raw count alone, determines inclusion.
              </Caption>
            </Stack>
          ) : null}
        </>
      )}
    </Stack>
  );
}

/** Whatever columns the envelope decided, in the order it decided them. */
function RecordTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return null;
  const keys = Object.keys(rows[0] ?? {});
  const columns: Column<Record<string, unknown>>[] = keys.map((key) => ({
    key,
    header: key,
    render: (row) => <span>{formatCell(row[key])}</span>,
  }));
  return <Table columns={columns} rows={rows} rowKey={(_row, index) => String(index)} />;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatCount(value);
  return String(value);
}

/** One row per (selected family, plain-language issue). Not one row per finding. */
export function Issues({ issues, family }: { issues: AggregatedIssue[]; family: Family }) {
  const heading = `Issues in selected family · ${FAMILY_LABEL[family]}`;
  if (issues.length === 0) {
    return (
      <Stack gap={6}>
        <h2>{heading}</h2>
        <Callout tone="info">This check ran. Nothing in this window.</Callout>
      </Stack>
    );
  }

  const columns: Column<AggregatedIssue>[] = [
    {
      key: "what",
      header: "What",
      help: help.COLUMNS.What,
      render: (row) => <span>{row.what || ""}</span>,
    },
    {
      key: "days",
      header: "Days",
      help: help.COLUMNS.Days,
      align: "right",
      width: 72,
      render: (row) => <span>{formatCount(row.days ?? 0)}</span>,
    },
    {
      key: "records",
      header: "Records",
      help: help.COLUMNS.Records,
      align: "right",
      width: 90,
      render: (row) => <span>{formatCount(row.records ?? 0)}</span>,
    },
    {
      key: "what_we_did",
      header: "What we did",
      help: help.COLUMNS["What we did"],
      render: (row) => <span>{row.what_we_did || ""}</span>,
    },
  ];

  return (
    <Stack gap={6}>
      <h2>{heading}</h2>
      <Table
        columns={columns}
        rows={issues}
        rowKey={(row, index) => `${row.what}-${index}`}
      />
    </Stack>
  );
}
