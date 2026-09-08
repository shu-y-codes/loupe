/**
 * The close look at the selected family: gap ribbon and pattern histogram.
 *
 * Both are SVG. The ribbon was a Vega chart under Streamlit because `st.html` was worse; here
 * there is no such trade — a row of twenty squares is twenty `<rect>`s, and drawing it
 * directly is both smaller and more legible than a chart grammar describing it.
 *
 * The histogram is the one place this app draws two series, and the pairing is the argument:
 * **Findings** against **Records (exposure)**, with a lift label per bucket. A bar chart of
 * finding counts alone would say a busy hour is a bad hour.
 */

import type { PatternBucket, PictureSlot } from "../api/types";
import { theme } from "../theme/theme";
import { Caption, Row, Text } from "../components/primitives";

/** Expected-vs-present minute slots around the hole. Present is filled; missing is not. */
export function GapRibbon({ slots }: { slots: PictureSlot[] }) {
  if (slots.length === 0) return <Caption>No slot ribbon for this gap.</Caption>;

  const box = 28;
  const gap = 3;
  const width = slots.length * (box + gap) + 8;
  const first = slots[0]?.label ?? "";
  const last = slots[slots.length - 1]?.label ?? "";

  return (
    <div style={{ overflowX: "auto" }}>
      <svg
        viewBox={`0 0 ${width} 56`}
        width={Math.min(width, 640)}
        role="img"
        aria-label="Expected minute slots around the gap"
      >
        {slots.map((slot, index) => (
          <rect
            key={`${slot.label}-${index}`}
            x={4 + index * (box + gap)}
            y={12}
            width={box}
            height={box}
            fill={slot.present ? theme.fill.secondary : theme.diff.stripRemoved}
            stroke={theme.stroke.primary}
            strokeWidth={1}
          >
            <title>{`${slot.label} · ${slot.present ? "present" : "missing"}`}</title>
          </rect>
        ))}
        <text x={4} y={52} fontSize={10} fill={theme.text.tertiary}>
          {first}
        </text>
        <text x={width - 4} y={52} fontSize={10} fill={theme.text.tertiary} textAnchor="end">
          {last}
        </text>
      </svg>
      <Row gap={14} wrap>
        <Row gap={5}>
          <svg width={12} height={12} aria-hidden="true">
            <rect
              width={12}
              height={12}
              fill={theme.fill.secondary}
              stroke={theme.stroke.primary}
            />
          </svg>
          <Text size="small" tone="secondary">
            Present
          </Text>
        </Row>
        <Row gap={5}>
          <svg width={12} height={12} aria-hidden="true">
            <rect width={12} height={12} fill={theme.diff.stripRemoved} />
          </svg>
          <Text size="small" tone="secondary">
            Missing
          </Text>
        </Row>
      </Row>
    </div>
  );
}

const WIDTH = 720;
const HEIGHT = 210;
const PAD_L = 52;
const PAD_R = 16;
const PAD_T = 22;
const PAD_B = 44;

/** Findings share against record exposure, per bucket, with the lift on top. */
export function PatternHistogram({
  buckets,
  axisLabel,
}: {
  buckets: PatternBucket[];
  axisLabel: string;
}) {
  if (buckets.length === 0) return null;

  const innerW = WIDTH - PAD_L - PAD_R;
  const innerH = HEIGHT - PAD_T - PAD_B;
  const top =
    Math.max(
      ...buckets.map((bucket) => Math.max(bucket.share_of_findings, bucket.share_of_records)),
    ) * 1.15 || 1;
  const n = buckets.length;
  const group = innerW / n;
  const barW = Math.min(24, (group * 0.7) / 2);
  const y = (share: number) => PAD_T + (1 - share / top) * innerH;

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Findings share against record exposure by ${axisLabel}`}
      >
        {[0, top / 2, top].map((value) => (
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
              {`${Math.round(value * 100)}%`}
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
          Share (%)
        </text>

        {buckets.map((bucket, index) => {
          const centre = PAD_L + (index + 0.5) * group;
          const hover =
            `${bucket.label} · findings ${(bucket.share_of_findings * 100).toFixed(1)}%` +
            ` · records ${(bucket.share_of_records * 100).toFixed(1)}%` +
            ` · lift ${bucket.lift.toFixed(1)}× · support ${bucket.support}` +
            ` · ${bucket.distinct_days} days`;
          const peak = Math.max(bucket.share_of_findings, bucket.share_of_records);
          return (
            <g key={bucket.label}>
              <title>{hover}</title>
              <rect
                x={centre - barW - 1}
                y={y(bucket.share_of_findings)}
                width={barW}
                height={Math.max(0, PAD_T + innerH - y(bucket.share_of_findings))}
                fill={theme.category.blue}
              />
              <rect
                x={centre + 1}
                y={y(bucket.share_of_records)}
                width={barW}
                height={Math.max(0, PAD_T + innerH - y(bucket.share_of_records))}
                fill={theme.fill.primary}
                stroke={theme.stroke.primary}
              />
              <text
                x={centre}
                y={y(peak) - 6}
                textAnchor="middle"
                fontSize={10}
                fontWeight={600}
                fill={theme.text.secondary}
              >
                {`${bucket.lift.toFixed(1)}×`}
              </text>
              <text
                x={centre}
                y={HEIGHT - 22}
                textAnchor="middle"
                fontSize={9}
                fill={theme.text.tertiary}
              >
                {bucket.label}
              </text>
            </g>
          );
        })}
        <text
          x={PAD_L + innerW / 2}
          y={HEIGHT - 6}
          textAnchor="middle"
          fontSize={11}
          fill={theme.text.tertiary}
        >
          {axisLabel}
        </text>
      </svg>
      <Row gap={14} wrap style={{ paddingLeft: PAD_L }}>
        <Row gap={5}>
          <svg width={12} height={12} aria-hidden="true">
            <rect width={12} height={12} fill={theme.category.blue} />
          </svg>
          <Text size="small" tone="secondary">
            Findings
          </Text>
        </Row>
        <Row gap={5}>
          <svg width={12} height={12} aria-hidden="true">
            <rect
              width={12}
              height={12}
              fill={theme.fill.primary}
              stroke={theme.stroke.primary}
            />
          </svg>
          <Text size="small" tone="secondary">
            Records (exposure)
          </Text>
        </Row>
      </Row>
    </div>
  );
}
