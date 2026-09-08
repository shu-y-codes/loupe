/**
 * Daily OHLCV and volume, drawn as SVG, keyed on the selected family.
 *
 * The grammar is the chart canvas's (`chart-issue-overlay.canvas.tsx`): triangle on a
 * session-open hole, a **dashed labelled column** where a settlement never arrived, a pin on a
 * kept duplicate, paint on an invalid candle, a band across a participating session, and
 * volume defects on the volume pane rather than the wick.
 *
 * What it never does: recolour by `max_severity`, and draw a zero-filled bar for a session
 * that produced no records. The absent column is the whole reason this is hand-drawn SVG.
 *
 * Price and volume share one x window — one `useZoom` over both panes, so they pan and zoom
 * together (`specs/loupe-ui-design.md`, Zoom and identity).
 */

import { useMemo } from "react";
import { theme } from "../theme/theme";
import { Caption, Row, Text } from "../components/primitives";
import { extremes, formatCount, formatNumber, shortDate, ticks } from "./scale";
import { legendEntries, overlayStatus, type LegendEntry, type Slot } from "./overlay";
import { useZoom } from "./useZoom";

export const OHLCV_ZOOM_CAPTION =
  "Drag the dates to pan, scroll to zoom. Double-click to reset.";

const WIDTH = 720;
const PRICE_HEIGHT = 300;
const VOLUME_HEIGHT = 88;
const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 32;

export interface OhlcvProps {
  slots: Slot[];
  family: string;
  scopeKey: string;
}

export function Ohlcv({ slots, family, scopeKey }: OhlcvProps) {
  const zoom = useZoom(slots.length, scopeKey);
  const visible = useMemo(
    () => slots.slice(zoom.extent.start, zoom.extent.end),
    [slots, zoom.extent.start, zoom.extent.end],
  );

  if (slots.length === 0) {
    return <Caption>No bars in this window.</Caption>;
  }

  const priced = visible.filter((slot) => slot.high !== null && slot.low !== null);
  const high = extremes(priced.map((slot) => slot.high as number));
  const low = extremes(priced.map((slot) => slot.low as number));
  const yMax = high?.max ?? 1;
  const yMin = low?.min ?? 0;
  const pad = (yMax - yMin) * 0.06 || 1;
  const top = yMax + pad;
  const bottom = yMin - pad;

  const innerW = WIDTH - PAD_L - PAD_R;
  const innerH = PRICE_HEIGHT - PAD_T - PAD_B;
  const n = Math.max(1, visible.length);
  const slotW = innerW / n;
  const xAt = (index: number) => PAD_L + ((index + 0.5) / n) * innerW;
  const y = (price: number) => PAD_T + ((top - price) / (top - bottom || 1)) * innerH;
  const bodyW = Math.min(10, slotW * 0.45);

  const maxVolume =
    extremes(visible.map((slot) => slot.volume).filter((v): v is number => v !== null))?.max ?? 0;
  const volInnerH = VOLUME_HEIGHT - 8 - 8;

  const gapColour = theme.diff.stripRemoved;
  const labelEvery = Math.max(1, Math.ceil(n / 12));

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${PRICE_HEIGHT}`}
        role="img"
        aria-label={`Daily OHLCV with ${family} overlay`}
        {...zoom.handlers}
      >
        {ticks(bottom, top).map((value) => (
          <g key={value}>
            <line
              x1={PAD_L}
              x2={WIDTH - PAD_R}
              y1={y(value)}
              y2={y(value)}
              stroke={theme.stroke.tertiary}
              strokeWidth={1}
            />
            <text
              x={PAD_L - 8}
              y={y(value) + 4}
              textAnchor="end"
              fontSize={10}
              fill={theme.text.tertiary}
            >
              {formatNumber(value)}
            </text>
          </g>
        ))}
        <text
          x={14}
          y={PAD_T + innerH / 2}
          fill={theme.text.tertiary}
          fontSize={11}
          transform={`rotate(-90 14 ${PAD_T + innerH / 2})`}
          textAnchor="middle"
        >
          Price
        </text>

        {visible.map((slot, index) => {
          const x = xAt(index);
          const status = overlayStatus(family, slot);
          const hover = hoverText(slot, status);

          // A holiday with no finding is not an absent settlement, and must not read as one.
          if (slot.session === "holiday") {
            return (
              // The hover sits on a wrapping `g` rather than inside the `text`: a `title`
              // child would join the label's own text content.
              <g key={slot.trade_date}>
                <title>{`${slot.trade_date} · holiday`}</title>
                <text
                  x={x}
                  y={PAD_T + innerH / 2}
                  textAnchor="middle"
                  fontSize={8}
                  fill={theme.text.quaternary}
                >
                  hol
                </text>
              </g>
            );
          }

          if (slot.open === null || slot.high === null || slot.low === null || slot.close === null) {
            // Settlement never arrived. A dashed labelled column, never a zero-filled bar.
            const lit = family === "gaps" || family === "patterns";
            return (
              <g key={slot.trade_date}>
                <title>{hover}</title>
                <line
                  x1={x}
                  x2={x}
                  y1={PAD_T}
                  y2={PAD_T + innerH}
                  stroke={lit ? gapColour : theme.stroke.tertiary}
                  strokeWidth={lit ? 1.5 : 1}
                  strokeDasharray={lit ? "4 3" : "2 4"}
                />
                {lit ? (
                  <text
                    x={x}
                    y={PAD_T + 12}
                    textAnchor="middle"
                    fontSize={8}
                    fill={gapColour}
                    fontWeight={600}
                  >
                    absent
                  </text>
                ) : null}
              </g>
            );
          }

          const yOpen = y(slot.open);
          const yClose = y(slot.close);
          const bodyTop = Math.min(yOpen, yClose);
          const bodyH = Math.max(2, Math.abs(yClose - yOpen));

          // Paint is for `invalid` alone: that is the family where the bar exists and a field
          // in it is impossible. A gap is missing time, so recolouring its candle would be a
          // lie about the close.
          let stroke: string = theme.mark.neutral;
          if (family === "invalid" && slot.invalid) stroke = theme.category.red;
          else if (family === "patterns" && slot.pattern_member) stroke = theme.category.blue;

          return (
            <g key={slot.trade_date}>
              <title>{hover}</title>
              {family === "patterns" && slot.pattern_member ? (
                <rect
                  x={x - slotW * 0.42}
                  y={PAD_T}
                  width={slotW * 0.84}
                  height={innerH}
                  fill={theme.category.blue}
                  opacity={0.12}
                />
              ) : null}
              <line x1={x} x2={x} y1={y(slot.high)} y2={y(slot.low)} stroke={stroke} strokeWidth={1.25} />
              <rect x={x - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={stroke} />
              {family === "gaps" && slot.partial_gap ? (
                <polygon
                  points={`${x},${y(slot.high) - 9} ${x - 4},${y(slot.high) - 3} ${x + 4},${y(slot.high) - 3}`}
                  fill={gapColour}
                />
              ) : null}
              {family === "duplicates" && slot.duplicate ? (
                <circle
                  cx={x}
                  cy={y(slot.low) + 8}
                  r={3.5}
                  fill={theme.accent.primary}
                  stroke={theme.bg.editor}
                  strokeWidth={1}
                />
              ) : null}
            </g>
          );
        })}

        {visible.map((slot, index) =>
          index % labelEvery === 0 ? (
            <text
              key={`x-${slot.trade_date}`}
              x={xAt(index)}
              y={PRICE_HEIGHT - 8}
              textAnchor="middle"
              fontSize={9}
              fill={theme.text.tertiary}
            >
              {shortDate(slot.trade_date)}
            </text>
          ) : null,
        )}
      </svg>

      <svg
        viewBox={`0 0 ${WIDTH} ${VOLUME_HEIGHT}`}
        role="img"
        aria-label="Daily volume"
        {...zoom.handlers}
      >
        <text
          x={14}
          y={8 + volInnerH / 2}
          fill={theme.text.tertiary}
          fontSize={11}
          transform={`rotate(-90 14 ${8 + volInnerH / 2})`}
          textAnchor="middle"
        >
          Volume
        </text>
        {visible.map((slot, index) => {
          if (slot.volume === null || !maxVolume) return null;
          const x = xAt(index);
          const height = (slot.volume / maxVolume) * volInnerH;
          const defect = family === "invalid" && slot.invalid_volume;
          return (
            <rect
              key={slot.trade_date}
              x={x - slotW * 0.28}
              y={8 + volInnerH - height}
              width={Math.max(1, slotW * 0.56)}
              height={height}
              fill={defect ? theme.category.orange : theme.mark.volume}
            >
              {/* Date, volume and status — never the raw colour-encoding field name. */}
              <title>
                {`${slot.trade_date} · volume ${formatCount(slot.volume)}` +
                  (defect ? " · volume defect" : "")}
              </title>
            </rect>
          );
        })}
      </svg>

      <Legend entries={legendEntries(family)} />
      <Caption>{OHLCV_ZOOM_CAPTION}</Caption>
    </div>
  );
}

function hoverText(slot: Slot, status: string): string {
  if (slot.open === null) return `${slot.trade_date} · ${status}`;
  return (
    `${slot.trade_date} · O ${formatNumber(slot.open)} · H ${formatNumber(slot.high ?? 0)}` +
    ` · L ${formatNumber(slot.low ?? 0)} · C ${formatNumber(slot.close ?? 0)} · ${status}`
  );
}

/** The selected family's marks, named. Not a proposal and not a list of dates. */
export function Legend({ entries }: { entries: LegendEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <Row gap={14} wrap style={{ padding: "4px 0 2px 56px" }}>
      {entries.map((entry) => (
        <Row key={entry.label} gap={5}>
          <svg width={16} height={12} aria-hidden="true">
            <Swatch entry={entry} />
          </svg>
          <Text size="small" tone="secondary">
            {entry.label}
          </Text>
        </Row>
      ))}
    </Row>
  );
}

function Swatch({ entry }: { entry: LegendEntry }) {
  switch (entry.shape) {
    case "triangle":
      return <polygon points="8,2 12,10 4,10" fill={entry.colour} />;
    case "dashed":
      return (
        <line
          x1={8}
          x2={8}
          y1={1}
          y2={11}
          stroke={entry.colour}
          strokeWidth={1.5}
          strokeDasharray="3 2"
        />
      );
    case "pin":
      return <circle cx={8} cy={6} r={3.5} fill={entry.colour} />;
    case "band":
      return <rect x={2} y={2} width={12} height={8} fill={entry.colour} opacity={0.25} />;
    case "cross":
      return (
        <g stroke={entry.colour} strokeWidth={1.5}>
          <line x1={4} x2={12} y1={6} y2={6} />
          <line x1={8} x2={8} y1={2} y2={10} />
        </g>
      );
    default:
      return <rect x={5} y={1} width={6} height={10} fill={entry.colour} />;
  }
}
