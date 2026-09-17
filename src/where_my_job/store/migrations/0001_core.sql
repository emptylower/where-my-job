-- src/where_my_job/store/migrations/0001_core.sql
-- 设计 v3 §4.1–§4.3。全部 15 表与 4 视图在此定型；后续子计划只写数据。
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INTEGER PRIMARY KEY,
  checksum    TEXT NOT NULL,
  applied_at  TEXT NOT NULL
);

CREATE TABLE companies (
  company_id         TEXT PRIMARY KEY,                 -- 'boss:<encryptBrandId>'
  source             TEXT NOT NULL,
  source_company_id  TEXT NOT NULL,
  name               TEXT,
  detail_evidence_id TEXT,                              -- 最近公司页证据（子计划 04）
  created_at         TEXT NOT NULL,
  updated_at         TEXT,
  UNIQUE (source, source_company_id)
);

CREATE TABLE runs (
  run_id         TEXT PRIMARY KEY,
  kind           TEXT NOT NULL CHECK (kind IN ('import','scan','deepdive','match')),
  status         TEXT NOT NULL CHECK (status IN ('running','ok','blocked','partial','failed','cancelled','interrupted')),
  parent_run_id  TEXT REFERENCES runs(run_id),
  config_json    TEXT NOT NULL CHECK (json_valid(config_json)),   -- 输入摘要（文件清单/策略/scoring 哈希）
  config_hash    TEXT NOT NULL,
  planned_count  INTEGER NOT NULL DEFAULT 0,
  completed_count INTEGER NOT NULL DEFAULT 0,
  started_at     TEXT NOT NULL,
  ended_at       TEXT,
  summary_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(summary_json))
);

CREATE TABLE run_tasks (
  task_id        TEXT PRIMARY KEY,
  run_id         TEXT NOT NULL REFERENCES runs(run_id),
  task_key       TEXT NOT NULL,                         -- import: 文件相对名；scan: kw|city|page；deepdive: job|company
  query_json     TEXT NOT NULL CHECK (json_valid(query_json)),
  status         TEXT NOT NULL CHECK (status IN ('planned','running','ok','empty','blocked','failed','skipped')),
  failure_code   TEXT,
  failure_message TEXT,
  response_key   TEXT,                                  -- 采集响应关联键
  started_at     TEXT,
  ended_at       TEXT,
  UNIQUE (run_id, task_key)
);
CREATE INDEX run_tasks_run_status ON run_tasks(run_id, status);

CREATE TABLE jobs (
  job_id               TEXT PRIMARY KEY,               -- 'boss:<encryptJobId>'
  source               TEXT NOT NULL,
  source_job_id        TEXT NOT NULL,
  legacy_job_id        TEXT,
  company_id           TEXT REFERENCES companies(company_id),
  current_sighting_id  TEXT,                            -- 最新有效观察；FK 延后到 sightings 建表后由触发器保证
  first_seen_at        TEXT,
  last_seen_at         TEXT,
  seen_run_count       INTEGER NOT NULL DEFAULT 0,
  hit_count            INTEGER NOT NULL DEFAULT 0,
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL,
  UNIQUE (source, source_job_id)
);
CREATE INDEX jobs_company ON jobs(company_id);
CREATE INDEX jobs_legacy ON jobs(legacy_job_id);

CREATE TABLE sightings (
  observation_id   TEXT PRIMARY KEY,
  job_id           TEXT NOT NULL REFERENCES jobs(job_id),
  run_id           TEXT NOT NULL REFERENCES runs(run_id),
  task_id          TEXT NOT NULL REFERENCES run_tasks(task_id),
  response_key     TEXT,                                -- 新采集
  file_sha256      TEXT,                                -- 旧导入
  item_index       INTEGER NOT NULL,
  page             INTEGER,
  observed_at      TEXT,                                -- 规范 UTC；来源没有时间时为 NULL，不用导入时刻补造
  observed_at_raw  TEXT,                                -- 来源原值
  time_precision   TEXT NOT NULL CHECK (time_precision IN ('response','file_snapshot')),
  tz_assumption    TEXT,
  raw_kind         TEXT NOT NULL CHECK (raw_kind IN ('api_entry','legacy_mapped')),
  raw_json         TEXT CHECK (raw_json IS NULL OR json_valid(raw_json)),   -- 私有；prune 后为 NULL
  raw_pruned_at    TEXT,
  fact_json        TEXT NOT NULL CHECK (json_valid(fact_json)),
  content_hash     TEXT NOT NULL,                       -- fact_hash
  raw_hash         TEXT,                                -- raw 的哈希，prune 后保留
  created_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX sightings_capture_key ON sightings(task_id, response_key, item_index) WHERE response_key IS NOT NULL;
CREATE UNIQUE INDEX sightings_file_key ON sightings(file_sha256, item_index) WHERE file_sha256 IS NOT NULL;
CREATE INDEX sightings_job_time ON sightings(job_id, observed_at);
CREATE INDEX sightings_run ON sightings(run_id);

CREATE TABLE evidence (
  evidence_id       TEXT PRIMARY KEY,
  job_id            TEXT REFERENCES jobs(job_id),
  company_id        TEXT REFERENCES companies(company_id),
  origin            TEXT NOT NULL CHECK (origin IN ('cli','agent','user')),
  kind              TEXT NOT NULL,                      -- job_detail_page | company_page | web_page | user_statement | document
  url               TEXT,
  captured_at       TEXT NOT NULL,
  published_at      TEXT,
  excerpt           TEXT,
  structured_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(structured_json)),
  full_text         TEXT,                               -- 原文；prune 后为 NULL
  full_text_pruned_at TEXT,
  content_hash      TEXT NOT NULL,
  parser_version    TEXT,
  completeness      TEXT NOT NULL CHECK (completeness IN ('complete','partial','unparsed')),
  source_note       TEXT,
  idempotency_key   TEXT NOT NULL UNIQUE,
  run_id            TEXT REFERENCES runs(run_id),
  created_at        TEXT NOT NULL,
  CHECK (job_id IS NOT NULL OR company_id IS NOT NULL)
);
CREATE INDEX evidence_job_time ON evidence(job_id, captured_at);
CREATE INDEX evidence_company_time ON evidence(company_id, captured_at);

CREATE TABLE evidence_bundles (
  bundle_id          TEXT PRIMARY KEY,
  job_id             TEXT NOT NULL REFERENCES jobs(job_id),
  run_id             TEXT REFERENCES runs(run_id),
  parent_bundle_id   TEXT REFERENCES evidence_bundles(bundle_id),
  evidence_ids_json  TEXT NOT NULL CHECK (json_valid(evidence_ids_json)),
  fact_sighting_id   TEXT REFERENCES sightings(observation_id),
  acquisition_state  TEXT NOT NULL CHECK (acquisition_state IN ('complete','partial')),
  unknowns_json      TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(unknowns_json)),
  bundle_version     INTEGER NOT NULL DEFAULT 1,
  created_at         TEXT NOT NULL
);
CREATE INDEX evidence_bundles_job ON evidence_bundles(job_id, created_at);

CREATE TABLE deepdives (
  report_id          TEXT PRIMARY KEY,
  job_id             TEXT NOT NULL REFERENCES jobs(job_id),
  bundle_id          TEXT NOT NULL REFERENCES evidence_bundles(bundle_id),
  report_md          TEXT NOT NULL CHECK (length(report_md) > 0),
  structured_json    TEXT NOT NULL CHECK (json_valid(structured_json)),   -- authentic / jd_translation / mismatches / resume_advice
  profile_revision   TEXT NOT NULL,
  report_version     INTEGER NOT NULL DEFAULT 1,
  idempotency_key    TEXT NOT NULL UNIQUE,
  created_at         TEXT NOT NULL
);
CREATE INDEX deepdives_job_time ON deepdives(job_id, created_at);

CREATE TABLE match_results (
  match_run_id           TEXT NOT NULL REFERENCES runs(run_id),
  job_id                 TEXT NOT NULL REFERENCES jobs(job_id),
  fact_revision          TEXT NOT NULL,
  scoring_hash           TEXT NOT NULL,
  profile_revision       TEXT NOT NULL,
  engine_version         TEXT NOT NULL,
  as_of                  TEXT NOT NULL,
  dir                    TEXT,
  excluded               INTEGER NOT NULL CHECK (excluded IN (0,1)),
  rule_score             REAL,
  tier                   TEXT,
  reasons_json           TEXT NOT NULL CHECK (json_valid(reasons_json)),
  exclusion_reasons_json TEXT NOT NULL CHECK (json_valid(exclusion_reasons_json)),
  unknowns_json          TEXT NOT NULL CHECK (json_valid(unknowns_json)),
  PRIMARY KEY (match_run_id, job_id)
);
CREATE INDEX match_results_run_score ON match_results(match_run_id, rule_score);

CREATE TABLE job_attrs (
  job_id            TEXT NOT NULL REFERENCES jobs(job_id),
  key               TEXT NOT NULL,
  value_json        TEXT NOT NULL CHECK (json_valid(value_json)),
  source            TEXT NOT NULL CHECK (source IN ('agent','user')),
  based_on_revision TEXT,
  updated_at        TEXT NOT NULL,
  PRIMARY KEY (job_id, key, source)
);

CREATE TABLE network_policy_state (
  browser_profile_id TEXT PRIMARY KEY,
  cooldown_until     TEXT,
  cooldown_reason    TEXT,
  ledger_json        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(ledger_json)),   -- [{at, kind, run_id}] 滚动 24h
  last_action_at     TEXT,
  policy_version     INTEGER NOT NULL DEFAULT 1,
  updated_at         TEXT NOT NULL
);

CREATE TABLE applications (
  application_id TEXT PRIMARY KEY,
  job_id         TEXT NOT NULL REFERENCES jobs(job_id),
  created_at     TEXT NOT NULL
);
CREATE INDEX applications_job ON applications(job_id);

CREATE TABLE stream_registry (
  stream          TEXT NOT NULL,
  stream_revision INTEGER NOT NULL,
  definition_json TEXT NOT NULL CHECK (json_valid(definition_json)),
  content_hash    TEXT NOT NULL,
  registered_at   TEXT NOT NULL,
  is_active       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (stream, stream_revision)
);

CREATE TABLE events (
  event_id           TEXT PRIMARY KEY,
  stream             TEXT NOT NULL,
  stream_revision    INTEGER NOT NULL,
  type               TEXT NOT NULL,
  subject_kind       TEXT NOT NULL CHECK (subject_kind IN ('job','company','application','none')),
  subject_id         TEXT,
  occurred_at        TEXT NOT NULL,
  recorded_at        TEXT NOT NULL,
  payload_json       TEXT NOT NULL CHECK (json_valid(payload_json)),
  idempotency_key    TEXT NOT NULL UNIQUE,
  corrected_event_id TEXT REFERENCES events(event_id),
  origin             TEXT NOT NULL CHECK (origin IN ('agent','user')),
  CHECK ((subject_kind = 'none') = (subject_id IS NULL)),
  FOREIGN KEY (stream, stream_revision) REFERENCES stream_registry(stream, stream_revision)
);
CREATE INDEX events_stream_subject ON events(stream, subject_kind, subject_id, occurred_at);
CREATE UNIQUE INDEX events_correction_target ON events(corrected_event_id) WHERE corrected_event_id IS NOT NULL;

-- 视图。列集合固定；未由本子计划填充的列先给 NULL/'[]'，由 02/03/04 的存储函数填数据。
CREATE VIEW v_runs AS
SELECT run_id, kind, status, parent_run_id, config_hash, planned_count, completed_count,
       started_at, ended_at, summary_json
FROM runs;

CREATE VIEW v_evidence AS
SELECT evidence_id, job_id, company_id, origin, kind, url, captured_at, published_at, excerpt,
       structured_json, content_hash, parser_version, completeness, source_note,
       CASE WHEN full_text IS NULL AND full_text_pruned_at IS NOT NULL THEN 'pruned'
            WHEN full_text IS NULL THEN 'absent' ELSE 'present' END AS full_text_state,
       created_at
FROM evidence;

CREATE VIEW v_events AS
SELECT e.event_id, e.stream, e.stream_revision, e.type, e.subject_kind, e.subject_id,
       e.occurred_at, e.recorded_at, e.payload_json, e.corrected_event_id, e.origin,
       (SELECT c.event_id FROM events c WHERE c.corrected_event_id = e.event_id) AS superseded_by
FROM events e;

-- v_jobs：设计 v3 §4.2 表格的全部列。match/attr/report/application 相关列由后续子计划的 SQL 填充，
-- 这里先按最终列集合建视图，未实现部分用常量占位，02/03/04 各自用 ALTER-free 的 "DROP VIEW + CREATE VIEW" 迁移替换。
CREATE VIEW v_jobs AS
SELECT
  1 AS view_schema_version,
  j.job_id,
  j.legacy_job_id,
  json_extract(s.fact_json, '$.title')            AS title,
  CASE WHEN j.source = 'boss' THEN 'https://www.zhipin.com/job_detail/' || j.source_job_id || '.html' END AS job_url,
  j.company_id,
  c.name                                          AS company_name,
  json_extract(s.fact_json, '$.city')             AS city,
  json_extract(s.fact_json, '$.district')         AS district,
  json_extract(s.fact_json, '$.salary_text')      AS salary_text,
  json_extract(s.fact_json, '$.salary_lo')        AS salary_lo,
  json_extract(s.fact_json, '$.salary_hi')        AS salary_hi,
  json_extract(s.fact_json, '$.salary_currency')  AS salary_currency,
  json_extract(s.fact_json, '$.salary_period')    AS salary_period,
  json_extract(s.fact_json, '$.pay_months')       AS pay_months,
  json_extract(s.fact_json, '$.exp')              AS exp,
  json_extract(s.fact_json, '$.degree')           AS degree,
  COALESCE(json_extract(s.fact_json, '$.skills'), '[]') AS skills_json,
  s.content_hash                                  AS fact_revision,
  j.first_seen_at, j.last_seen_at, j.seen_run_count, j.hit_count,
  NULL AS match_run_id, NULL AS dir, 'missing' AS match_state, NULL AS rule_score,
  0.0 AS score_adjustment, NULL AS score, NULL AS tier, '[]' AS reasons_json,
  NULL AS excluded, '[]' AS exclusion_reasons_json,
  COALESCE(json_extract(s.fact_json, '$.unknowns'), '[]') AS unknowns_json,
  NULL AS priority,
  NULL AS current_bundle_id, NULL AS report_id, 'none' AS report_state,
  NULL AS application_id, NULL AS application_state, 0 AS followup_due
FROM jobs j
LEFT JOIN sightings s ON s.observation_id = j.current_sighting_id
LEFT JOIN companies c ON c.company_id = j.company_id;
