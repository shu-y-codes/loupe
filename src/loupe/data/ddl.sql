-- Loupe schema. Normative source: specs/data-model.md.
-- The only deviation from the spec text is IF NOT EXISTS / OR REPLACE, so that
-- apply_schema() is idempotent. Shapes, keys and constraints are as specified.

CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS stage;
CREATE SCHEMA IF NOT EXISTS dq;
CREATE SCHEMA IF NOT EXISTS mart;

-- ---------------------------------------------------------------- ref

CREATE TABLE IF NOT EXISTS ref.contract (
  contract_id       VARCHAR PRIMARY KEY,   -- as it appears in the source, e.g. 'ESZ25'
  root              VARCHAR NOT NULL,      -- 'ES'; may be three characters, e.g. 'SR3'
  root_id           VARCHAR,               -- vendor's own product identifier
  month_code        VARCHAR,               -- 'Z'
  contract_month    DATE,                  -- 2025-12-01
  exchange          VARCHAR,               -- no default: six exchanges in the sample
  timezone          VARCHAR DEFAULT 'America/Chicago',  -- vendor normalisation, not a venue property
  tick_size         DOUBLE,                -- default only; VAL.OFF_TICK_PRICE reads ref.tick
  multiplier        DOUBLE,                -- contract terms, not measurable from prices
  first_trade_date  DATE,
  last_trade_date   DATE,
  roll_date         DATE,
  parse_confidence  DOUBLE,
  dates_inferred    BOOLEAN DEFAULT TRUE,
  created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ref.product (
  root         VARCHAR PRIMARY KEY,
  description  VARCHAR,
  exchange     VARCHAR,
  timezone     VARCHAR,
  tick_size    DOUBLE,
  multiplier   DOUBLE,
  cycle        VARCHAR,
  session_open_local   TIME,   -- 17:00:00
  session_close_local  TIME,   -- 16:00:00, on the *following* calendar day for most roots
  spans_midnight       BOOLEAN GENERATED ALWAYS AS
                       (session_open_local > session_close_local) VIRTUAL,
  halt_windows JSON            -- a list of INTRA-session halts; ZC has one, ES none
);

CREATE TABLE IF NOT EXISTS ref.tick (
  root       VARCHAR NOT NULL,
  frequency  VARCHAR NOT NULL CHECK (frequency IN ('minute','daily')),
  field      VARCHAR NOT NULL CHECK (field IN ('open','high','low','close')),
  tick_size  DOUBLE,                -- null: do not apply VAL.OFF_TICK_PRICE to this field
  exempt     BOOLEAN DEFAULT FALSE, -- true for settlement-bearing daily close
  PRIMARY KEY (root, frequency, field)
);

CREATE TABLE IF NOT EXISTS ref.session_calendar (
  exchange             VARCHAR,
  root                 VARCHAR,
  trade_date           DATE,
  session_open_utc     TIMESTAMPTZ,
  session_close_utc    TIMESTAMPTZ,
  is_holiday           BOOLEAN DEFAULT FALSE,
  is_early_close       BOOLEAN DEFAULT FALSE,
  halt_windows_utc     JSON,
  expected_slots_1m    BIGINT,   -- 1380 for a full CME-family session; per root and per date
  PRIMARY KEY (exchange, root, trade_date)
);

-- -------------------------------------------------------------- stage

CREATE TABLE IF NOT EXISTS stage.ingest_batch (
  batch_id        UUID PRIMARY KEY DEFAULT uuid(),
  filename        VARCHAR NOT NULL,
  file_hash       VARCHAR NOT NULL,          -- sha256 of file bytes
  file_bytes      BIGINT,
  file_format     VARCHAR CHECK (file_format IN ('csv','parquet')),
  status          VARCHAR NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','running','succeeded','partial','failed','purged')),
  rows_read       BIGINT DEFAULT 0,
  rows_accepted   BIGINT DEFAULT 0,
  rows_rejected   BIGINT DEFAULT 0,
  column_mapping  JSON,      -- not a bijection: one source column may feed a derived pair
  frequency       VARCHAR NOT NULL CHECK (frequency IN ('minute','daily')),
  bar_interval    VARCHAR,   -- '1 minute', '1 day'
  source_timezone VARCHAR,
  ts_convention   VARCHAR CHECK (ts_convention IN ('interval_start','interval_end')),
  session_boundary VARCHAR,
  inferred_interval VARCHAR,
  interval_confidence DOUBLE,
  error_summary   JSON,
  started_at      TIMESTAMPTZ DEFAULT now(),
  finished_at     TIMESTAMPTZ,
  UNIQUE (file_hash)
);

CREATE SEQUENCE IF NOT EXISTS stage.seq_record_id;

CREATE TABLE IF NOT EXISTS stage.market_record (
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
  open_interest BIGINT,
  ingested_at   TIMESTAMPTZ DEFAULT now()
);

-- The logical key (contract_id, frequency, ts_utc) is deliberately NOT unique:
-- duplicates must be loadable so that they can be detected, reported and scored.
CREATE INDEX IF NOT EXISTS idx_mr_lookup  ON stage.market_record (contract_id, frequency, ts_utc);
CREATE INDEX IF NOT EXISTS idx_mr_session ON stage.market_record (contract_id, frequency, trade_date);

CREATE TABLE IF NOT EXISTS stage.record_reject (
  batch_id      UUID    NOT NULL,
  source_row    BIGINT  NOT NULL,
  reason_code   VARCHAR NOT NULL,   -- STR.* codes; specs/dq-rules-and-scoring.md owns them
  reason_detail VARCHAR,
  raw_payload   VARCHAR,            -- the original row, verbatim
  PRIMARY KEY (batch_id, source_row)
);

-- ----------------------------------------------------------------- dq

CREATE TABLE IF NOT EXISTS dq.dq_rule (
  rule_id     VARCHAR PRIMARY KEY,
  dimension   VARCHAR NOT NULL CHECK (dimension IN
                ('completeness','uniqueness','validity','consistency','timeliness',
                 'reconciliation')),
  name        VARCHAR NOT NULL,
  description VARCHAR,
  severity    VARCHAR NOT NULL CHECK (severity IN ('info','warning','error','critical')),
  scope       VARCHAR NOT NULL CHECK (scope IN ('record','session','series','file')),
  applies_to_frequency VARCHAR,                -- null = every granularity
  params      JSON,
  enabled     BOOLEAN DEFAULT TRUE,
  weight      DOUBLE  DEFAULT 1.0,
  origin      VARCHAR DEFAULT 'builtin' CHECK (origin IN ('builtin','suggested','user')),
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dq.dq_run (
  run_id        UUID PRIMARY KEY DEFAULT uuid(),
  batch_id      UUID,                  -- null for a re-run over an existing corpus
  ruleset_hash  VARCHAR,
  scope_filter  JSON,
  status        VARCHAR DEFAULT 'running'
                CHECK (status IN ('running','succeeded','failed')),
  findings_count BIGINT,
  started_at    TIMESTAMPTZ DEFAULT now(),
  finished_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS dq.dq_finding (
  finding_id    UUID PRIMARY KEY DEFAULT uuid(),
  run_id        UUID    NOT NULL,
  rule_id       VARCHAR NOT NULL,
  contract_id   VARCHAR,
  frequency     VARCHAR,          -- the granularity this finding is about; a grouping key
  compare_frequency VARCHAR,      -- reconciliation findings only: the other side
  trade_date    DATE,
  ts_start_utc  TIMESTAMPTZ,      -- a range, so a gap is one row not 1380
  ts_end_utc    TIMESTAMPTZ,
  record_id     BIGINT,
  affected_rows BIGINT DEFAULT 1,
  severity      VARCHAR NOT NULL,
  details       JSON,             -- evidence; never grouped on
  status        VARCHAR DEFAULT 'open'
                CHECK (status IN ('open','accepted','overridden','resolved')),
  reviewed_by   VARCHAR,
  reviewed_at   TIMESTAMPTZ,
  review_note   VARCHAR,
  detected_at   TIMESTAMPTZ DEFAULT now(),
  CHECK ((compare_frequency IS NULL) OR (frequency IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_finding_slice ON dq.dq_finding (contract_id, trade_date, rule_id);
CREATE INDEX IF NOT EXISTS idx_finding_freq  ON dq.dq_finding (contract_id, frequency, trade_date);

CREATE TABLE IF NOT EXISTS dq.cleaning_action (
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

-- Raw records are immutable; the clean basis is derived from the decision log.
CREATE OR REPLACE VIEW dq.market_record_clean AS
SELECT r.*
FROM stage.market_record r
WHERE NOT EXISTS (
  SELECT 1 FROM dq.cleaning_action a
  WHERE a.record_id = r.record_id
    AND a.action IN ('exclude','dedupe_drop')
);

-- --------------------------------------------------------------- mart

CREATE TABLE IF NOT EXISTS mart.bar_daily (
  contract_id      VARCHAR NOT NULL,
  trade_date       DATE    NOT NULL,
  basis            VARCHAR NOT NULL CHECK (basis IN ('raw','clean')),
  source           VARCHAR NOT NULL CHECK (source IN ('derived','vendor')),
  source_frequency VARCHAR NOT NULL,   -- 'minute' when derived, 'daily' when supplied
  session_boundary VARCHAR,
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

CREATE TABLE IF NOT EXISTS mart.dq_metric_daily (
  contract_id     VARCHAR NOT NULL,
  trade_date      DATE    NOT NULL,
  frequency       VARCHAR NOT NULL,   -- a granularity, or 'cross' for the reconciliation rollup
  dimension       VARCHAR NOT NULL,
  expected_records BIGINT,
  actual_records   BIGINT,
  affected_records BIGINT,
  finding_count    BIGINT,
  dimension_score  DOUBLE,     -- 0-100
  PRIMARY KEY (contract_id, trade_date, frequency, dimension)
);
