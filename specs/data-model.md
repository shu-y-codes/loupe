# Loupe — Data model

**Normative.** DuckDB schema and the invariants that go with it. Promoted from research
`_notes/cursor/03-data-model.md` (now archaeology). Sample-derived claims cited here are owned
by `specs/sample-corpus.md`. Summary and layer boundaries: `specs/loupe-solution-design.md`
§6, §7, §10.

Revised 2026-09-08: `user` / `role` still absent; the UI is Review + Overview, not a
role view selector. Revised 2026-09-05: promoted from research; first normative version.

Validated against DuckDB 1.4.5. `UUID`, `JSON`, `TIMESTAMPTZ`, `CHECK`, `PRIMARY KEY`,
`UNIQUE`, `DEFAULT uuid()`, `DEFAULT now()`, `GENERATED ALWAYS AS ... VIRTUAL` and table-level
`CHECK` spanning two columns all behave as written. The DDL below applies as one script in
dependency order.

---

## 1. Layering

Four schemas, mapping onto the layer separation in the solution design:

```
ref     reference data          contract, product, tick, session_calendar
stage   as-loaded, immutable    ingest_batch, market_record, record_reject
dq      quality                 dq_rule, score_weight, dq_run, dq_finding, cleaning_action
mart    derived analytics       bar_daily, vwap_15m (view), dq_metric_daily
```

**`stage.market_record` is append-only and is never updated or deleted.** Cleaning is expressed
as rows in `dq.cleaning_action` and surfaced through `dq.market_record_clean`. Every number in
the application is therefore reproducible from the source file plus the ruleset, the changelog
comes for free, and the same query runs over `raw` and `clean` so the delta is showable. This is
locked decision 1.

---

## 2. `ref` — reference data

```sql
CREATE SCHEMA IF NOT EXISTS ref;

CREATE TABLE ref.contract (
  contract_id       VARCHAR PRIMARY KEY,   -- as it appears in the source, e.g. 'ESZ25'
  root              VARCHAR NOT NULL,      -- 'ES'; may be three characters, e.g. 'SR3'
  root_id           VARCHAR,               -- vendor's own product identifier, e.g. 'ROOT#100042'
  month_code        VARCHAR,               -- 'Z'
  contract_month    DATE,                  -- 2025-12-01
  exchange          VARCHAR,               -- no default; see below
  timezone          VARCHAR DEFAULT 'America/Chicago',
  tick_size         DOUBLE,                -- traded tick, e.g. 0.25 for ES; default only, see ref.tick
  multiplier        DOUBLE,                -- 50.0
  first_trade_date  DATE,                  -- listing; observed if not in reference data
  last_trade_date   DATE,                  -- expiry; observed if not in reference data
  roll_date         DATE,                  -- volume migration, for suppression near expiry
  parse_confidence  DOUBLE,                -- symbology is vendor-dependent; record how sure
  dates_inferred    BOOLEAN DEFAULT TRUE,  -- true when derived from data, not reference
  created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE ref.product (
  root         VARCHAR PRIMARY KEY,
  description  VARCHAR,
  exchange     VARCHAR,
  timezone     VARCHAR,
  tick_size    DOUBLE,
  multiplier   DOUBLE,
  cycle        VARCHAR,        -- 'quarterly' | 'monthly' | comma-separated month codes
  session_open_local   TIME,   -- 17:00:00
  session_close_local  TIME,   -- 16:00:00, on the *following* calendar day for most roots
  spans_midnight       BOOLEAN GENERATED ALWAYS AS
                       (session_open_local > session_close_local) VIRTUAL,
  halt_windows JSON            -- a list of INTRA-session halts; ZC has one, ES none
);

CREATE TABLE ref.tick (
  root       VARCHAR NOT NULL,
  frequency  VARCHAR NOT NULL CHECK (frequency IN ('minute','daily')),
  field      VARCHAR NOT NULL CHECK (field IN ('open','high','low','close')),
  tick_size  DOUBLE,                -- null means "do not apply VAL.OFF_TICK_PRICE to this field"
  exempt     BOOLEAN DEFAULT FALSE, -- true for settlement-bearing daily close
  PRIMARY KEY (root, frequency, field)
);

CREATE TABLE ref.session_calendar (
  exchange             VARCHAR,
  root                 VARCHAR,
  trade_date           DATE,
  session_open_utc     TIMESTAMPTZ,
  session_close_utc    TIMESTAMPTZ,
  is_holiday           BOOLEAN DEFAULT FALSE,
  is_early_close       BOOLEAN DEFAULT FALSE,
  halt_windows_utc     JSON,
  expected_slots_1m    BIGINT,   -- 1380 for a full CME-family session
  PRIMARY KEY (exchange, root, trade_date)
);
```

### 2.1 Rules that go with these tables

**`ref.session_calendar` is generated, not hand-maintained.** On first sight of a contract,
expand `ref.product` rules plus a seeded holiday list across the date range present in the data.
Materialising it rather than computing sessions inline keeps the session definition in one place
and makes it inspectable and testable.

**`expected_slots_1m` is per root and per date, never a constant.** The sample corpus runs 1,380
slots for the five CME-family roots, 570 for SB and 1,055 for ZC. VX observes 1,381 on three
rows out of 373,886; seed VX on the CME profile at 1,380 and let those three rows raise a
warning. Counts and profiles are owned by `specs/sample-corpus.md` §4.

**`exchange` has no default.** Six exchanges are present in the sample — CBOT, CFE, CME, COMEX,
ICEUS, NYMEX — and CFE and ICEUS are not CME Group venues, so a `'CME'` default would be
silently wrong for a third of the corpus and would survive every test run against ES. The value
is a source column and also the grandparent directory of each file, so it is cheap to populate
and cheap to cross-check. Where a vendor supplies neither, a null exchange is more honest than a
guessed one.

**`timezone` keeps a default, but it is a vendor normalisation, not an exchange property.** This
vendor expresses every venue's timestamps in Chicago wall clock, including ICE Sugar, whose
session it pinned to a fixed 02:30–11:59 Chicago window rather than tracking London's DST
calendar. `America/Chicago` is the correct *seeded default for this vendor*, and the seed belongs
with the vendor profile that also supplies `column_mapping` and `session_boundary`. A feed
stamping in exchange-local time per venue would seed a different value per root; nothing else in
the model changes.

**`root_id` carries the vendor's product identifier verbatim.** It is not used for joins — `root`
is — but it is the handle for a support conversation with the publisher and for detecting that a
vendor has quietly renumbered a product.

**Sessions cross midnight; `session_open_local > session_close_local` is the normal case.** For
five of the eight roots in the sample the session opens at 17:00 and closes at 16:00 on the
*following* calendar day. There is deliberately **no** `CHECK (session_open_local <
session_close_local)`; such a constraint would reject the majority of real products.
`spans_midnight` is generated so the condition is computed once in the schema rather than
restated in every predicate, and containment must branch on it:

```sql
CASE WHEN p.spans_midnight
     THEN t >= p.session_open_local OR  t <= p.session_close_local
     ELSE t >= p.session_open_local AND t <= p.session_close_local
END
```

**`halt_windows` is a list of windows, not one window, and it holds *intra-session* halts
only.** A session made of N contiguous blocks carries N−1 halts; the gap between one session's
close and the next one's open is already expressed by `session_open_local` /
`session_close_local` and must not be repeated here, or the expected grid is short by the
length of the overnight break. So the CME-family 16:00–16:59 dead zone is **not** a halt — it
falls outside a 17:00→16:00 session — while ZC's 07:45–08:29 break **is**, because it splits one
session into two blocks (19:00–07:44 and 08:30–13:19).

The invariant this buys, and which the seeding tests assert: **`expected_slots_1m` equals the
session span in minutes minus the halted minutes.** ES 23 h − 0 = 1,380; SB 9 h 30 − 0 = 570;
ZC 18 h 20 − 45 = 1,055.

The seeding logic, the UTC expansion into `halt_windows_utc` and the expected-slot grid
generator must all iterate the list. A single-window implementation passes every test written
against ES and fails only on the one root nobody demonstrates.

**`ref.contract.tick_size` is the default *traded* increment and is not sufficient on its own.**
`VAL.OFF_TICK_PRICE` must be keyed by `(root, frequency, field)`: VX minute prices sit on a 0.01
lattice with zero exceptions in 373,886 rows, while VX daily `close` is off-tick in 805 of 959
rows because that column is a settlement carried to four decimals. Settlement-bearing fields are
marked `exempt` rather than given a fake lattice; seed the rest from the data as the largest
increment on which every observed price of that triple lies.
`specs/dq-rules-and-scoring.md` owns the rule; this table is the grain it needs.

---

## 3. `stage` — ingestion and raw records

```sql
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE stage.ingest_batch (
  batch_id        UUID PRIMARY KEY DEFAULT uuid(),
  filename        VARCHAR NOT NULL,
  file_hash       VARCHAR NOT NULL,          -- sha256 of file bytes
  file_bytes      BIGINT,
  file_format     VARCHAR CHECK (file_format IN ('csv','parquet')),
  origin          VARCHAR NOT NULL DEFAULT 'upload'   -- 'upload' | 'demo' | 'injected'
                  CHECK (origin IN ('upload','demo','injected')),
  status          VARCHAR NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','running','succeeded','partial','failed','purged')),
  rows_read       BIGINT DEFAULT 0,
  rows_accepted   BIGINT DEFAULT 0,
  rows_rejected   BIGINT DEFAULT 0,
  column_mapping  JSON,      -- not a bijection; see below
  frequency       VARCHAR NOT NULL CHECK (frequency IN ('minute','daily')),
  bar_interval    VARCHAR,   -- '1 minute', '1 day'
  source_timezone VARCHAR,   -- declared or inferred
  ts_convention   VARCHAR CHECK (ts_convention IN ('interval_start','interval_end')),
  session_boundary VARCHAR,  -- '17:00 America/Chicago' | 'calendar_date' | 'column:trading_date'
  inferred_interval VARCHAR, -- '1 minute'
  interval_confidence DOUBLE,
  error_summary   JSON,
  started_at      TIMESTAMPTZ DEFAULT now(),
  finished_at     TIMESTAMPTZ,
  UNIQUE (file_hash)
);
```

**`UNIQUE (file_hash)` gives idempotent re-upload.** The same file twice is rejected at the door
rather than silently doubling every volume figure. The API surfaces this as **409**.

**`pending` and `running` stay in the status enum although ingestion is synchronous.** They are
transient states inside a single request, not something a client polls. They exist for crash
recovery and observability: a load that dies part-way leaves a row at `running` with a null
`finished_at`, which is both the signal and the handle for cleaning up its partial rows.

`column_mapping`, `frequency`, `bar_interval`, `source_timezone`, `ts_convention`,
`session_boundary` and `inferred_interval` are the ingestion decisions made per file. Persisting
them is what makes a result explainable six months later, and it is where file-shape
extensibility lives: a new vendor layout is a new mapping, not new code.

**`column_mapping` is not a bijection.** A realistic mapping for this vendor's minute files:

```json
{
  "contract_symbol": "contract_id",
  "timestamp_chicago_wall": ["ts_exchange", "ts_utc"],
  "timestamp_ms": "ts_source",
  "open": "open", "high": "high", "low": "low", "close": "close",
  "volume": "volume"
}
```

One source column feeds a *derived pair*: the naive wall-clock label populates `ts_exchange`
directly and `ts_utc` by attaching `source_timezone`, so the right-hand side may be a list. Two
source columns carry the same instant in different forms, so the mapping also records *which one
we chose to trust* — the wall clock, because the integer alongside it is a Chicago reading rather
than an epoch instant and reading it as epoch-milliseconds shifts every record by five or six
hours. The vendor's `trading_date` and `minute_of_day` columns are deliberately unmapped;
`trading_date` disagrees with the vendor's own daily boundary and we derive the session date
instead. An unmapped source column is recorded as absent from the mapping rather than omitted
silently, so the preview endpoint can show that a column was seen and rejected.

**`session_boundary` is a first-class ingestion decision.** The trade-date boundary is not
recoverable from the loaded rows once the wrong one has been applied, and getting it wrong is
close to undetectable: on this corpus a calendar-date boundary produces exactly the right
expected slot count for a CME session with entirely the wrong membership, and drops agreement
with the vendor's daily bars from about 98% to about 20% while raising no record-level finding.
Persisting the boundary makes "which definition produced this bar" answerable and makes
reprocessing a batch-scoped operation rather than a guess.

**`frequency` and `bar_interval` are recorded per batch as well as per record.** The batch value
is the declared or inferred property of the *file* and is what preview shows before commit; the
record value keeps the two granularities apart in storage. Stored twice on purpose: a file that
turns out to be mixed is a quality finding we want to express, not a contradiction that cannot be
represented. `bar_interval` carries the interval as text — `'1 minute'`, `'1 day'` — so a
five-minute or hourly feed needs a new value, not a new column.

```sql
CREATE SEQUENCE stage.seq_record_id;

CREATE TABLE stage.market_record (
  record_id     BIGINT PRIMARY KEY DEFAULT nextval('stage.seq_record_id'),
  batch_id      UUID NOT NULL,
  source_row    BIGINT NOT NULL,      -- 1-based row in the source file
  contract_id   VARCHAR NOT NULL,
  frequency     VARCHAR NOT NULL CHECK (frequency IN ('minute','daily')),
  ts_source     VARCHAR NOT NULL,     -- source timestamp label, verbatim and unparsed
  ts_exchange   TIMESTAMP   NOT NULL, -- exchange wall clock, as the source labelled it
  ts_utc        TIMESTAMPTZ NOT NULL, -- derived: ts_exchange at the batch's source_timezone
  trade_date    DATE        NOT NULL, -- session date, assigned at ingest
  open          DOUBLE,
  high          DOUBLE,
  low           DOUBLE,
  close         DOUBLE,
  volume        BIGINT,
  volume_source VARCHAR,             -- verbatim volume label, ONLY when it is not an integer
  open_interest BIGINT,
  ingested_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_mr_lookup  ON stage.market_record (contract_id, frequency, ts_utc);
CREATE INDEX idx_mr_session ON stage.market_record (contract_id, frequency, trade_date);
```

### 3.1 Six deliberate choices

**OHLCV columns are nullable.** A null price is a *quality finding*, not a load failure. If the
loader rejects it, the user can never see it, and "detect missing values" becomes impossible to
demonstrate. Only rows that cannot be *parsed* are rejected. This is the line between
`stage.market_record` and `stage.record_reject`, and it belongs in the delivered README.

**The logical record key is `(contract_id, frequency, ts_utc)`, and it is deliberately not
enforced.** Duplicates must be *loadable* so they can be *detected*. Enforcing uniqueness here
would push duplicate detection into the loader's exception handler, where it cannot be reported,
scored or overridden. Both indexes lead with the three-column key, because every lookup, every
session aggregation and the duplicate rule itself are three-column operations. An index on
`(contract_id, ts_utc)` would answer no question the application asks: nothing legitimately wants
both granularities of one contract interleaved on one timeline.

**`volume_source` exists so that `VAL.NON_INTEGER_VOLUME` can fire.** Volume is a count of
contracts, so the column stays `BIGINT` — but DuckDB casts the string `'10.5'` to `11` rather
than refusing it, so a fractional volume is numeric enough to load and the fraction is gone by
the time any rule could see it. `'10.5'` is also not `STR.NON_NUMERIC_VOLUME`: that code is for
a value that is not a number at all, and conflating the two would reject the whole row and lose
its OHLC as well. Ingest therefore keeps the verbatim label **only when it does not parse as an
integer**, so the column is null for every one of the 5.3 million clean rows and non-null exactly
where there is something to report.

**`source_row` is carried on every record.** This is the traceability spine: every finding can
say "row 41,207 of `ESZ25.parquet`". Without it, drill-down stops at the database boundary.

**`ts_utc` is derived; `ts_source` preserves what the file said.** There is no UTC instant
anywhere in this vendor's source — only a DST-aware Chicago wall clock and an integer rendering
to the same wall-clock reading, neither of which is an instant. `ts_utc` is produced by attaching
the batch's `source_timezone` to `ts_exchange`, which makes it a *conclusion* about the data and
therefore something that can be wrong. `ts_source` holds the original label verbatim and unparsed
so that if the timezone conclusion is corrected, reprocessing is a query over `stage` rather than
a re-read of a file that may no longer exist. It is `VARCHAR` rather than `BIGINT` because the
source label is an epoch-style integer for this vendor and an ISO-8601 string, a date/time pair,
or a broker-specific format for others; nothing joins on it.

**`open_interest` is nullable and is a real source column.** This vendor's daily files carry it
on all 30,102 rows, 20.43% of them zero; its minute files do not carry it at all. Null therefore
means "not supplied at this granularity" and zero means "supplied as zero" — a deferred contract
with genuine zero open interest and one whose open interest was never reported are different
situations. Open interest is a *stock*, not a flow, so it is never summed across bars; it carries
through to `mart.bar_daily` as the last reported value for the session.

**`frequency` is what stops the two granularities colliding.** See §3.2.

### 3.2 Frequency as a first-class property

This vendor publishes every contract twice: a one-minute tape and a daily summary, in separate
files with different column sets. Both are legitimate uploads, and a user with a daily file and
no minute file still deserves a working application.

Without a discriminator, loading both files for one contract is a **correctness bug, not an
inconvenience**. A daily row must be stamped with some instant to occupy `ts_utc`, and every
available choice collides with a minute bar that already exists. Stamping at the session open
puts it on the same key as that session's 17:00 minute bar; stamping at midnight collides with
the 00:00 minute bar, and CME-family products trade through midnight. `ESZ25` alone — 114,477
minute rows and 1,145 daily rows — produces 102 colliding `(contract_id, ts_utc)` pairs under the
session-open convention and 79 under the midnight convention. With `frequency` in the key, both
figures are zero.

The consequence of getting this wrong is worse than a warning. `UNQ.KEY_CONFLICT` would fire on
every one of those pairs and report good data as duplicated, the uniqueness score would collapse
for exactly the contracts we have most data about, and the default cleaning policy for a key
conflict with differing values is to *exclude all conflicting rows* — so the default remediation
would delete real market data in response to a modelling error.

**Loupe accepts both granularities and never rejects an upload on granularity.** Gating is on
file format only. What the user supplied determines which capabilities light up:

| Uploaded | Daily bars | 15-minute VWAP | Reconciliation |
|---|---|---|---|
| Minute only | Derived from the minute tape | Available | Not possible |
| Daily only | Ingested as supplied | Unavailable — no intraday rows to weight | Not possible |
| Both | Derived, and compared against the supplied bars | Available | Available |

A daily-only upload cannot produce a rolling 15-minute VWAP at all, and the honest response is an
explicit "unavailable, because the uploaded file has no intraday rows" rather than an empty chart
or an interpolated fiction.

`CHECK (frequency IN ('minute','daily'))` enumerates the two values this vendor ships, not the
two values Loupe can ever hold. The column is an interval *label*; adding five-minute or hourly
data is a widened `CHECK` plus a row in the session-slot configuration — no key changes, no new
tables, no change to any query already carrying the column. Code that genuinely needs to know
whether a granularity is intraday — the VWAP view, rules scoped by `applies_to_frequency` —
should ask that of `bar_interval` rather than testing `frequency = 'minute'`.

```sql
CREATE TABLE stage.record_reject (
  batch_id      UUID    NOT NULL,
  source_row    BIGINT  NOT NULL,
  reason_code   VARCHAR NOT NULL,   -- STR.* codes, see specs/dq-rules-and-scoring.md
  reason_detail VARCHAR,
  raw_payload   VARCHAR,            -- the original line, verbatim
  PRIMARY KEY (batch_id, source_row)
);
```

Rejects are row-level, not file-level. A file with 3 unparseable rows out of 400,000 loads with
status `partial`; it is not thrown away. The exercise asks for malformed *records* to be handled,
and this table is where partial acceptance lives. It must be visible in the UI, or the rejected
rows are as invisible as if they had been dropped.

---

## 4. `dq` — rules, runs, findings, cleaning

Rule identifiers, severities, thresholds and the score formula are owned by
`specs/dq-rules-and-scoring.md`. This section owns the storage.

```sql
CREATE SCHEMA IF NOT EXISTS dq;

CREATE TABLE dq.dq_rule (
  rule_id     VARCHAR PRIMARY KEY,            -- 'CON.HIGH_LT_LOW'
  dimension   VARCHAR NOT NULL CHECK (dimension IN
                ('completeness','uniqueness','validity','consistency','timeliness',
                 'reconciliation')),
  name        VARCHAR NOT NULL,
  description VARCHAR,
  severity    VARCHAR NOT NULL CHECK (severity IN ('info','warning','error','critical')),
  scope       VARCHAR NOT NULL CHECK (scope IN ('record','session','series','file')),
  applies_to_frequency VARCHAR,                -- null = every granularity
  params      JSON,                            -- thresholds, tunable without a code change
  enabled     BOOLEAN DEFAULT TRUE,
  triage_weight DOUBLE DEFAULT 1.0,           -- worklist ordering ONLY; never a score input
  origin      VARCHAR DEFAULT 'builtin' CHECK (origin IN ('builtin','suggested','user')),
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

**Rules are data, not code branches.** This is what makes "suggest cleansing or validation rules"
a real feature: an accepted suggestion writes a row here with `origin = 'suggested'` and the next
run picks it up. (v1 reports suggestions only — locked decision 10 — but the storage is what
keeps that an extension rather than a rewrite.)

`reconciliation` joins the five conventional dimensions because comparing two granularities of
one contract is a different kind of check: every other dimension can be evaluated against one set
of records, and this one cannot be evaluated at all unless two were supplied. Keeping it separate
rather than folding it into `consistency` means its contribution can be omitted honestly when
only one granularity is present, instead of a consistency score that silently means different
things depending on the upload.

`applies_to_frequency` exists because several rules are sound at one granularity and noise at
another. A rule asserting that a bar with a range implies non-zero volume holds on the minute
tape and is false of a daily summary containing settlement-only rows; a tick lattice every minute
price satisfies is violated by almost every daily settlement. Null means the rule applies
everywhere, keeping the common case free of ceremony.

```sql
CREATE TABLE dq.score_weight (
  dimension VARCHAR PRIMARY KEY CHECK (dimension IN
              ('completeness','uniqueness','validity','consistency','timeliness',
               'reconciliation')),
  weight    DOUBLE NOT NULL,      -- the ONLY weights in the score (dq-rules-and-scoring 11.2)
  enabled   BOOLEAN DEFAULT TRUE
);

CREATE TABLE dq.dq_run (
  run_id        UUID PRIMARY KEY DEFAULT uuid(),
  batch_id      UUID,                  -- null for a re-run over an existing corpus
  ruleset_hash  VARCHAR,               -- hash of enabled rules + params
  scope_filter  JSON,                  -- {"contract_id":"ESZ25","frequency":"minute","start":"..."}
  status        VARCHAR DEFAULT 'running'
                CHECK (status IN ('running','succeeded','failed')),
  findings_count BIGINT,
  started_at    TIMESTAMPTZ DEFAULT now(),
  finished_at   TIMESTAMPTZ
);
```

**`origin` is provenance, and it is a column because it has to outlive a session.** A demo can
plant labelled synthetic defects to show rules the vendor corpus cannot trigger
(`specs/loupe-solution-design.md` §9), and from that moment every score and finding count drawn
from those records is partly manufactured. A UI flag would be gone on the next reload; a
filename convention would be a guess. The column travels with the records, survives a restart,
and is what `GET /v1/health` counts so no surface can report a number without the disclosure.

It is a **declaration by the caller** and changes nothing about how a file is read. `demo` is
real vendor data loaded by the demo button; only `injected` is manufactured.

`ruleset_hash` makes results reproducible and answers "why did this number change?" — either the
data changed or the ruleset did, and the hash says which.

```sql
CREATE TABLE dq.dq_finding (
  finding_id    UUID PRIMARY KEY DEFAULT uuid(),
  run_id        UUID    NOT NULL,
  rule_id       VARCHAR NOT NULL,
  contract_id   VARCHAR,
  frequency     VARCHAR,          -- the granularity this finding is about
  compare_frequency VARCHAR,      -- reconciliation findings only: the other side
  trade_date    DATE,
  ts_start_utc  TIMESTAMPTZ,      -- a range, so a gap is one row not 1380
  ts_end_utc    TIMESTAMPTZ,
  record_id     BIGINT,           -- set when scope = 'record'
  affected_rows BIGINT DEFAULT 1,
  severity      VARCHAR NOT NULL,
  details       JSON,             -- {"field":"high","observed":1250.3,"expected":"multiple of 0.25"}
  status        VARCHAR DEFAULT 'open'
                CHECK (status IN ('open','accepted','overridden','resolved')),
  reviewed_by   VARCHAR,
  reviewed_at   TIMESTAMPTZ,
  review_note   VARCHAR,
  detected_at   TIMESTAMPTZ DEFAULT now(),
  CHECK ((compare_frequency IS NULL) OR (frequency IS NOT NULL))
);

CREATE INDEX idx_finding_slice ON dq.dq_finding (contract_id, trade_date, rule_id);
CREATE INDEX idx_finding_freq  ON dq.dq_finding (contract_id, frequency, trade_date);
```

`ts_start_utc` / `ts_end_utc` as a range rather than a point is what makes run-length-encoded gaps
representable. `affected_rows` keeps counts honest when one finding covers many slots.

**Reconciliation findings live in this table, with two columns rather than JSON.** A
reconciliation finding has the same identity, severity, review lifecycle and drill-down as any
other; a second table would duplicate all of that and force every list, count and review screen to
read from two places.

It does need two real columns. `frequency` is a **grouping key**: `mart.dq_metric_daily`
aggregates findings per granularity, the UI filters by it, and the same rule genuinely produces
different verdicts on the two configs of one contract, so a query that cannot group by it cannot
produce a correct score. Extracting a grouping key from a JSON document on every aggregation is
the wrong shape and defeats the index. `compare_frequency` exists because a reconciliation finding
is about a *pair*, and one column cannot say which two things disagreed. Which side lands in
which column is fixed by `specs/dq-rules-and-scoring.md` §8 — `frequency` is the side the
finding is a statement about — because downstream selection filters on it; a non-null value is also
the cheapest predicate for "show me the cross-frequency findings" without pattern-matching on rule
identifiers. The table-level `CHECK` enforces that the pair is well-formed.

Everything below the pair stays in `details` JSON, because it is per-rule and never grouped on:
which field disagreed, both values, the absolute difference, the volume ratio, the count of minute
rows behind the derived bar. Keys get columns; evidence gets JSON.

A `(contract_id, trade_date)` comparison across granularities is recorded as one row per
disagreeing field, with the evidence in `details` and the pair oriented by the rule's own claim,
which `idx_finding_freq` serves directly. `REC.OHLC_DISAGREE` says the vendor's stated high is
wrong, so it is `frequency = 'daily'`, `compare_frequency = 'minute'`; `REC.VOLUME_SHORTFALL`
says the *tape* is short and reverses the pair. `REC.SESSION_ONLY_IN_ONE` takes the side that
holds the session, so a session present in the daily file with no minute rows behind it is a
finding *about* the daily side. The table is §8's, not this section's.

The `status` / `reviewed_*` columns are storage for the analyst review journey. **v1 writes
`open` and reads it back**; override is an extension (locked decision 10).

```sql
CREATE TABLE dq.cleaning_action (
  action_id   UUID PRIMARY KEY DEFAULT uuid(),
  run_id      UUID NOT NULL,
  record_id   BIGINT NOT NULL,
  rule_id     VARCHAR,
  action      VARCHAR NOT NULL
              CHECK (action IN ('exclude','dedupe_drop','coerce','impute')),
  field       VARCHAR,
  old_value   VARCHAR,
  new_value   VARCHAR,
  rationale   VARCHAR,
  applied_at  TIMESTAMPTZ DEFAULT now()
);
```

This is the changelog, expressed as a log of *decisions* rather than an audit of in-place edits.
Nothing in `stage.market_record` is ever mutated.

```sql
CREATE VIEW dq.market_record_clean AS
SELECT r.*
FROM stage.market_record r
WHERE NOT EXISTS (
  SELECT 1 FROM dq.cleaning_action a
  WHERE a.record_id = r.record_id
    AND a.action IN ('exclude','dedupe_drop')
);
```

Every analytic query takes a `basis` parameter and reads either `stage.market_record` or
`dq.market_record_clean`. One switch, two answers, and the difference is the quantified cost of
the quality problem.

**The view needs no change for frequency, and that is exactly the risk.** `SELECT r.*` propagates
`frequency`, `ts_source` and `open_interest` automatically, and cleaning is keyed on `record_id`,
which is unique across granularities. But a view that silently carries both granularities will
let a caller aggregate millions of minute rows and thousands of daily rows into one nonsense bar.
**Every read of either the table or the view must carry a `frequency` predicate**, and a query
that touches `stage.market_record` without one is a defect in review. The query helpers therefore
take frequency as a *required* argument alongside `basis`, so the two decisions that determine
what a number means are both explicit at every call site.

### 4.1 Default cleaning policy

All configurable, all logged. Owned jointly with `specs/dq-rules-and-scoring.md`, which sets the
rule IDs.

| Condition | Action |
|---|---|
| Exact duplicate row | `dedupe_drop`, keep lowest `source_row` |
| `(contract_id, frequency, ts_utc)` conflict with differing values | `exclude` all conflicting rows — you cannot know which is right |
| `high < low` | `exclude` |
| Non-positive price | `exclude` |
| Negative volume | `exclude` |
| Off-tick price | flag only, do not exclude — tick reference data may be wrong |
| Statistical outlier | flag only, never exclude |

The last two matter. Auto-excluding an outlier deletes exactly the price action a trader is
looking for, and on real data the tick reference is the likelier culprit: the sample's daily
settlements sit off the lattice for one root on 83.9% of rows, which is a reference-data problem
masquerading as thousands of bad prices.

**Duplicate and conflict rules are evaluated within a frequency, never across.** Two rows
agreeing on `(contract_id, ts_utc)` but differing on `frequency` are not duplicates; they are a
daily summary and a minute bar sharing a timestamp, and treating them as a conflict would exclude
both.

---

## 5. `mart` — derived analytics

```sql
CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE mart.bar_daily (
  contract_id      VARCHAR NOT NULL,
  trade_date       DATE    NOT NULL,
  basis            VARCHAR NOT NULL CHECK (basis IN ('raw','clean')),
  source           VARCHAR NOT NULL CHECK (source IN ('derived','vendor')),
  source_frequency VARCHAR NOT NULL,   -- 'minute' when derived, 'daily' when supplied
  session_boundary VARCHAR,            -- which boundary produced this bar
  close_convention VARCHAR CHECK (close_convention IN ('last_trade','settlement')),
  open             DOUBLE,
  high             DOUBLE,
  low              DOUBLE,
  close            DOUBLE,
  volume           BIGINT,
  open_interest    BIGINT,             -- last reported for the session; never summed
  first_ts_utc     TIMESTAMPTZ,
  last_ts_utc      TIMESTAMPTZ,
  record_count     BIGINT,
  expected_count   BIGINT,
  completeness_pct DOUBLE,
  volume_null_count BIGINT,
  finding_count    BIGINT,
  max_severity     VARCHAR,
  computed_at      TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (contract_id, trade_date, basis, source)
);
```

The quality columns on the fact row are the point: a bar and its trustworthiness travel together,
so the UI never joins across tabs to shade a candle.

**A `source` discriminator in the key, not a second table.** A daily bar computed from the minute
tape and a daily bar the vendor supplied are different objects that must both be representable for
the same `(contract_id, trade_date)`, because comparing them is the whole point of the
reconciliation dimension. The discriminator wins on three counts. The column sets are identical, so
a separate `mart.bar_daily_vendor` would restate a dozen columns and oblige every reader to know
which table to consult. The comparison becomes a self-join on the natural key —
`d.source = 'derived'` against `v.source = 'vendor'` on `(contract_id, trade_date)` — which is the
query the reconciliation rules run. And the discriminator makes the asymmetry impossible to
forget: with one table, a request for bars *must* say which source it wants.

`basis` and `source` are orthogonal and both belong in the key. `basis` says whether the quality
findings were acted on; `source` says where the bar came from. Vendor rows are records in
`stage.market_record` like any other, so they are subject to cleaning and legitimately have both a
raw and a clean form — the sample contains 43 daily rows whose settlement close falls outside the
traded range, exactly the kind of row a cleaning policy may exclude. Four rows per
contract-session is the maximum; one or two is realistic.

Three provenance columns come with the discriminator, because `source` alone does not say what a
bar *means*:

- **`source_frequency`** records the granularity the bar was built from. `'minute'` for a derived
  bar today; naming it is what lets a derived bar later come from five-minute or hourly data and
  still be a derived daily bar.
- **`session_boundary`** records which trade-date definition produced the bar. Users will ask,
  because this vendor ships a `trading_date` column that disagrees with its own daily files, and
  `basis` cannot answer it. Two bars for the same contract and date can differ solely because of
  the boundary; without this column the difference is unattributable.
- **`close_convention`** distinguishes a last-trade close from a settlement. The vendor's daily
  close is struck near 15:00 local and is a settlement, so it may legitimately fall outside
  `[low, high]`, and does on 0.143% of the sample's daily rows. An invariant check treating a
  settlement bar like a derived bar reports the vendor's normal behaviour as corruption. It is
  also what lets `REC.CLOSE_CONVENTION` explain a disagreement rather than merely report one.

Several quality columns are meaningful only for derived bars, deliberately. A vendor daily bar has
`record_count = 1` and no useful `expected_count` or `completeness_pct`, because one supplied row
is not a sample of an expected grid of one-minute slots. Nulls there are the honest encoding:
completeness of a vendor daily bar is a statement about the daily series, which
`mart.dq_metric_daily` carries at series level.

```sql
CREATE TABLE mart.dq_metric_daily (
  contract_id     VARCHAR NOT NULL,
  trade_date      DATE    NOT NULL,
  frequency       VARCHAR NOT NULL,   -- a granularity, or 'cross' for the reconciliation rollup
  dimension       VARCHAR NOT NULL,
  expected_records BIGINT,
  actual_records   BIGINT,
  affected_records BIGINT,
  finding_count    BIGINT,
  dimension_score  DOUBLE,     -- 0-100, see specs/dq-rules-and-scoring.md
  PRIMARY KEY (contract_id, trade_date, frequency, dimension)
);
```

Pre-aggregating per contract per day per dimension makes trend charts and pattern detection cheap.
Both "identify recurring data quality patterns" and the DQ trend widget read this one table.

**Write it set-based.** The composite key is what makes a re-run idempotent, and it is also what
makes a per-row upsert pathological: `INSERT OR REPLACE` one row at a time is an index probe, a
possible delete and an insert, repeated once per row. Measured on this corpus, the same 145,236
rows take **159 seconds** row by row and **0.1 seconds** as a single `INSERT OR REPLACE ... SELECT`.
The rows are the result of a query, so they never need to reach Python at all — which is already
how `stage.market_record` is written (§3). Anywhere rows genuinely originate in Python, insert
them in chunks of one statement rather than one statement per row.

**`frequency` belongs in this key.** Without it the two granularities of one contract-day average
into a single score, and on this corpus they genuinely disagree: the same root scores perfectly on
the tick lattice in its minute config and badly in its daily config. Averaging produces a number
describing neither file, which moves when the *mix* of uploaded files changes rather than when the
data changes. Splitting the key also makes frequency available as a pattern dimension and lets the
UI say "your minute data is clean, your daily data has a tick problem".

`frequency` carries no `CHECK` here, unlike on the record and batch tables. It holds any
granularity label the record table can hold, plus the sentinel `'cross'` for
`dimension = 'reconciliation'` rows, whose subject is a *pair*. The pair is recoverable from the
underlying findings. **Reconciliation rows are absent, not zero, when only one granularity was
uploaded** — a null score is the truthful way to say the check was not possible; a zero would read
as "reconciliation failed".

VWAP is a **view**, not a table — cheap to compute, parameterised by window and price basis, and
not worth materialising at this scale:

```sql
CREATE VIEW mart.vwap_15m AS ...   -- definition owned by specs/analytics-semantics.md
```

The view reads intraday records only and must filter on `frequency`. A daily row cannot contribute
to a rolling 15-minute window, so a daily-only corpus yields an empty result, and the API reports
that as *unavailable* rather than as an empty series. This is the one capability granularity
genuinely gates, and it gates the output, not the upload.

---

## 6. Deliberately absent

| Not modelled | Why |
|---|---|
| `user`, `role`, `role_view` | No authentication in v1. The UI is Review + Overview, not a role view selector. |
| `report_catalog`, `chart` registry | Registry indirection for a fixed set of charts is cost without benefit. Add it when the set becomes user-extensible. |
| Bid/ask, or any quote-level data | Genuinely not in the source. Only aggregated bars are supplied, so no spread, depth or quote-based check is possible. |
| A separate settlement-price column | Not needed rather than not available. The vendor's daily `close` **is** a settlement price, so it is stored in `close` on a `source = 'vendor'` bar and distinguished by `close_convention`. A parallel column would be null on every minute-derived bar and would duplicate what the discriminator already says. |
| Continuous / back-adjusted contract series | The natural next feature, and out of scope for v1. Named in the README as the top extension; `ref.contract.roll_date` already exists to support it. |
