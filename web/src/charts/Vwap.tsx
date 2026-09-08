/**
 * The rolling 15-minute VWAP line, with its own x zoom.
 *
 * Null windows are a **break**, not a connected line — the path restarts rather than joining
 * across them, which is the whole point (`specs/analytics-semantics.md`). When the selected
 * family is Gaps, Recurring patterns or Invalid values and the envelope says the breaks are
 * nameable, crosses name them; patterns additionally shade the concentrating hour.
 *
 * Its zoom identity changes with contract or From / To but **not** with family, so it is a
 * separate `useZoom` from Daily OHLCV rather than a shared one.
 */

import { useMemo } from "react";
import type { VwapPoint } from "../api/types";
import { theme } from "../theme/theme";
import { Caption } from "../components/primitives";
import { bucketSeries, extremes, formatNumber, shortTime, ticks } from "./scale";
import { hourFromBucket } from "./overlay";
import { Legend } from "./Ohlcv";
import { useZoom } from "./useZoom";

export const VWAP_ZOOM_CAPTION =
  "Drag the timestamps to pan, scroll to zoom. Double-click to reset.";

const WIDTH = 720;
const HEIGHT = 200;
const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 28;

/**
 * Marks drawn across the pane, at most.
 *
 * A minute tape is a hundred thousand points and the pane is 720 units wide, so drawing one
 * mark per point would put 160 of them on every pixel — and, before that, would build a path
 * string nobody can render. `bucketSeries` reduces how many observed points are *drawn*; it
 * changes no value and never hides a break.
 */
const MARK_BUDGET = 720;

export interface VwapProps {
  points: VwapPoint[];
  family: string;
  vwapMeta: { name_breaks?: boolean; pattern_hours?: string[] } | undefined;
  /** False at Daily quality grain: the line stays as context, the family marks do not. */
  showFamilyMarks: boolean;
  nameBreaks: boolean;
  scopeKey: string;
}

export function Vwap({
  points,
  family,
  vwapMeta,
  showFamilyMarks,
  nameBreaks,
  scopeKey,
}: VwapProps) {
  const zoom = useZoom(points.length, scopeKey);
  const visible = useMemo(
    () => points.slice(zoom.extent.start, zoom.extent.end),
    [points, zoom.extent.start, zoom.extent.end],
  );

  if (points.length === 0) return <Caption>No VWAP points in this window.</Caption>;

  const marks = bucketSeries(visible, MARK_BUDGET, (point) => point.vwap);
  const bounds = extremes(
    marks.map((mark) => mark.value).filter((value): value is number => value !== null),
  );
  const high = bounds?.max ?? 1;
  const low = bounds?.min ?? 0;
  const pad = (high - low) * 0.08 || 1;
  const top = high + pad;
  const bottom = low - pad;

  const innerW = WIDTH - PAD_L - PAD_R;
  const innerH = HEIGHT - PAD_T - PAD_B;
  const n = Math.max(1, marks.length);
  const xAt = (index: number) => PAD_L + ((index + 0.5) / n) * innerW;
  const y = (value: number) => PAD_T + ((top - value) / (top - bottom || 1)) * innerH;
  const slotW = innerW / n;

  // A break restarts the path. One `d` with `M` at every resumption, so a null window is a
  // hole in the line rather than a straight segment across it.
  let pen = "M";
  const path = marks
    .map((mark, index) => {
      if (mark.broken || mark.value === null) {
        pen = "M";
        return "";
      }
      const segment = `${pen} ${xAt(index)} ${y(mark.value)}`;
      pen = "L";
      return segment;
    })
    .filter(Boolean)
    .join(" ");

  const shadedHours = new Set(
    showFamilyMarks && family === "patterns"
      ? (vwapMeta?.pattern_hours ?? [])
          .map(hourFromBucket)
          .filter((hour): hour is number => hour !== null)
      : [],
  );
  const breakY = bounds ? y((high + low) / 2) : PAD_T + innerH / 2;
  const labelEvery = Math.max(1, Math.ceil(n / 10));

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Rolling 15-minute VWAP${showFamilyMarks ? ` with ${family} marks` : ""}`}
        {...zoom.handlers}
      >
        {ticks(bottom, top, 3).map((value) => (
          <g key={value}>
            <line
              x1={PAD_L}
              x2={WIDTH - PAD_R}
              y1={y(value)}
              y2={y(value)}
              stroke={theme.stroke.tertiary}
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
          VWAP
        </text>

        {marks.map(({ point }, index) =>
          shadedHours.has(new Date(point.ts_utc).getUTCHours()) ? (
            <rect
              key={`band-${point.ts_utc}`}
              x={xAt(index) - slotW / 2}
              y={PAD_T}
              width={slotW}
              height={innerH}
              fill={theme.category.blue}
              opacity={0.12}
            />
          ) : null,
        )}

        <path d={path} fill="none" stroke={theme.text.secondary} strokeWidth={1.75} />

        {nameBreaks
          ? marks.map(({ point, broken }, index) =>
              broken ? (
                <g
                  key={`break-${point.ts_utc}`}
                  stroke={theme.diff.stripRemoved}
                  strokeWidth={1.5}
                >
                  <title>{`${shortTime(point.ts_utc)} · window volume was dropped`}</title>
                  <line x1={xAt(index) - 5} x2={xAt(index) + 5} y1={breakY} y2={breakY} />
                  <line x1={xAt(index)} x2={xAt(index)} y1={breakY - 6} y2={breakY + 6} />
                </g>
              ) : null,
            )
          : null}

        {marks.map(({ point }, index) =>
          index % labelEvery === 0 ? (
            <text
              key={`x-${point.ts_utc}`}
              x={xAt(index)}
              y={HEIGHT - 8}
              textAnchor="middle"
              fontSize={9}
              fill={theme.text.tertiary}
            >
              {shortTime(point.ts_utc)}
            </text>
          ) : null,
        )}
      </svg>

      {nameBreaks ? (
        <>
          <Legend
            entries={[
              {
                label: "Window volume dropped",
                colour: "var(--diff-strip-removed)",
                shape: "cross",
              },
            ]}
          />
          <Caption>Crosses name a break where window volume was dropped.</Caption>
        </>
      ) : null}
      <Caption>{VWAP_ZOOM_CAPTION}</Caption>
    </div>
  );
}
