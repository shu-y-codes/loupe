/**
 * The sidebar: the page switch, then Review-only filters, then the demo panel.
 *
 * The sidebar is the whole of the page's input surface. There is **no file uploader** and no
 * persona radio. Overview | Review is a destination switch, not a persona selector, and its
 * only Review chrome is the switch itself (`specs/loupe-ui-design.md`, Navigation).
 *
 * Overview-only means exactly that: no contract picker, no Quality grain control and no
 * From / To when Overview is showing. The demo panel is shared, so an empty store can reach
 * Load demo data from either destination without bouncing.
 */

import type { Contract, Frequency } from "../api/types";
import type { AppActions, AppState, Destination } from "../state";
import { heldGrains } from "../state";
import { theme } from "../theme/theme";
import { Caption, Divider, Pill, Row, Stack, Text } from "./primitives";

const PAGES: Destination[] = ["Overview", "Review"];

export function Sidebar({
  state,
  contracts,
  children,
}: {
  state: AppState & AppActions;
  contracts: Contract[];
  /** The demo panel. Shared across destinations, so it is passed rather than imported. */
  children?: React.ReactNode;
}) {
  const selected = contracts.find((row) => row.contract_id === state.contract);
  const available = heldGrains(selected);

  return (
    <nav
      aria-label="Loupe"
      style={{
        width: "var(--sidebar-width)",
        flex: "0 0 var(--sidebar-width)",
        borderRight: `1px solid ${theme.stroke.secondary}`,
        background: theme.bg.sunken,
        padding: 16,
        overflowY: "auto",
      }}
    >
      <Stack gap={14}>
        {/* A wordmark, not a heading. The main column carries the page's one `h1`
            (`specs/loupe-ui-design.md`, Review header: "Under **Loupe**, show …"), and a
            second `Loupe` heading here would give the page two competing titles. */}
        <div style={{ fontSize: "var(--size-h1)", fontWeight: 600 }}>Loupe</div>

        <Stack gap={4}>
          <Text size="small" tone="secondary">
            Page
          </Text>
          <Row gap={6} role="group" aria-label="Page">
            {PAGES.map((page) => (
              <Pill
                key={page}
                active={state.destination === page}
                onClick={() => state.setDestination(page)}
              >
                {page}
              </Pill>
            ))}
          </Row>
        </Stack>

        {state.destination === "Review" ? (
          <>
            <Divider />
            <Stack gap={4}>
              <label htmlFor="contract" style={{ fontSize: "var(--size-small)" }}>
                Contract
              </label>
              {contracts.length ? (
                <select
                  id="contract"
                  value={state.contract ?? ""}
                  onChange={(event) => state.setContract(event.target.value || null)}
                  style={selectStyle}
                >
                  {contracts.map((row) => (
                    <option key={row.contract_id} value={row.contract_id}>
                      {row.contract_id}
                    </option>
                  ))}
                </select>
              ) : (
                <Caption>No contracts loaded yet.</Caption>
              )}
            </Stack>

            {available.length > 1 ? (
              <Stack gap={4}>
                <Text size="small" tone="secondary">
                  Quality grain
                </Text>
                <Row gap={6} role="group" aria-label="Quality grain">
                  {available.map((grain) => (
                    <Pill
                      key={grain}
                      active={state.frequency === grain}
                      onClick={() => state.setFrequency(grain)}
                    >
                      {grain === "minute" ? "Minute" : "Daily"}
                    </Pill>
                  ))}
                </Row>
              </Stack>
            ) : available.length === 1 ? (
              // A single-grain contract has no choice to offer, so it gets quiet context
              // instead of a control with one option.
              <Caption>{`Quality grain · ${grainLabel(available[0])}`}</Caption>
            ) : null}

            <Divider />
            <Stack gap={6}>
              <h3>Trade dates</h3>
              <DateField
                id="start"
                label="From"
                value={state.start}
                onChange={state.setStart}
              />
              <DateField id="end" label="To" value={state.end} onChange={state.setEnd} />
            </Stack>
          </>
        ) : null}

        <Divider />
        {children}
      </Stack>
    </nav>
  );
}

function grainLabel(grain: Frequency | undefined): string {
  return grain === "minute" ? "Minute" : "Daily";
}

function DateField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <Stack gap={2}>
      <label htmlFor={id} style={{ fontSize: "var(--size-small)" }}>
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        style={selectStyle}
      />
    </Stack>
  );
}

const selectStyle: React.CSSProperties = {
  border: `1px solid ${theme.stroke.primary}`,
  borderRadius: "var(--radius)",
  background: theme.bg.editor,
  padding: "4px 6px",
  fontSize: "var(--size-body)",
  width: "100%",
};
