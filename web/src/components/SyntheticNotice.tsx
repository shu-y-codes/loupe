/**
 * The disclosure that has to survive every interaction.
 *
 * Driven by `/v1/health`, which the shell calls before it draws anything, so this cannot be
 * skipped by a code path that forgot: there is no route to either destination that does not
 * pass through it. A one-time toast at the moment of injection would be gone three
 * interactions later, with a screen full of findings and nothing saying nine of them were
 * manufactured.
 *
 * A warning **Callout**, not `⚠️`. The emoji was doing the work of saying "this matters";
 * a titled block with a coloured rule says it in the page's own language.
 */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Health, InjectionResponse } from "../api/types";
import type { Column } from "./primitives";
import { Callout, Caption, Stack, Table, Text } from "./primitives";

export function SyntheticNotice({ health }: { health: Health }) {
  const synthetic = health.synthetic_batches ?? 0;
  const [injection, setInjection] = useState<InjectionResponse | null>(null);

  useEffect(() => {
    if (!synthetic) {
      setInjection(null);
      return;
    }
    let live = true;
    api
      .injection()
      .then((body) => {
        if (live) setInjection(body);
      })
      .catch(() => {
        if (live) setInjection(null);
      });
    return () => {
      live = false;
    };
  }, [synthetic]);

  if (!synthetic) return null;

  return (
    <Stack gap={8}>
      <Callout tone="warning" title="This store contains planted defects" role="alert">
        {`${(health.synthetic_records ?? 0).toLocaleString("en-US")} of ` +
          `${(health.records ?? 0).toLocaleString("en-US")} records come from a deliberately ` +
          "corrupted copy of one file, loaded to demonstrate rules the real corpus cannot " +
          "trigger. Scores, finding counts and patterns below are partly synthetic. Remove " +
          "them from the sidebar to return to real vendor data."}
      </Callout>
      <Manifest injection={injection} />
    </Stack>
  );
}

/**
 * The evidence, where the reviewer is rather than only on disk.
 *
 * The manifest names the rule each planted defect should trip. Showing it is what turns "some
 * of this is fake" into something a reader can check, and it is the difference between a
 * labelled injection and a corrupted file. Grouping is the server's
 * (`GET /v1/demo/injection`) — this component never imports the catalogue map.
 */
function Manifest({ injection }: { injection: InjectionResponse | null }) {
  if (!injection) return null;
  if (!injection.manifest_available) {
    return (
      <Caption>
        The planted manifest is not on disk, so what was planted cannot be listed here.
      </Caption>
    );
  }

  const columns: Column<InjectionResponse["groups"][number]["defects"][number]>[] = [
    { key: "row", header: "Row", align: "right", width: 64, render: (d) => <span>{d.source_row ?? "—"}</span> },
    { key: "rule", header: "Rule", render: (d) => <code>{d.rule_id}</code> },
    { key: "kind", header: "What was done", render: (d) => <span>{d.kind}</span> },
    { key: "was", header: "Was", render: (d) => <span>{d.original ?? "—"}</span> },
    { key: "now", header: "Now", render: (d) => <span>{d.injected ?? "—"}</span> },
  ];

  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: "var(--size-small)" }}>
        What was planted
      </summary>
      <Stack gap={10} style={{ paddingTop: 8 }}>
        <Caption>
          {`${injection.source ?? ""} → ${injection.output ?? ""} · ` +
            `${(injection.rows_in ?? 0).toLocaleString("en-US")} rows in, ` +
            `${(injection.rows_out ?? 0).toLocaleString("en-US")} out · seed ${injection.seed ?? "—"}`}
        </Caption>
        {injection.groups.map((group) => (
          <Stack key={group.family} gap={4}>
            <Text weight="semibold">{group.label}</Text>
            {injection.filename ? <Caption>{injection.filename}</Caption> : null}
            <Table
              columns={columns}
              rows={group.defects}
              rowKey={(defect, index) => `${defect.rule_id}-${index}`}
            />
          </Stack>
        ))}
      </Stack>
    </details>
  );
}
