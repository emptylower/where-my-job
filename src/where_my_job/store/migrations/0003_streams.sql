-- src/where_my_job/store/migrations/0003_streams.sql
-- 子计划 03：内置流注册、有效事件视图、投递状态视图；文件末尾的 v_jobs 重建由生成器写入，禁止手改。
-- 内置 applications 定义与 streams/builtin.py 的 APPLICATIONS_DEFINITION 逐字一致；content_hash 由 test_builtin_hash_matches_migration 核对。
INSERT INTO stream_registry(stream, stream_revision, definition_json, content_hash, registered_at, is_active)
VALUES ('applications', 1,
 '{"schema_version":1,"stream":"applications","stream_revision":1,"subject_kind":"application","types":{"applied":{"required":["job_id"],"fields":{"job_id":"string","channel":"string","note":"string"}},"replied":{"required":[],"fields":{"note":"string"}},"interview":{"required":[],"fields":{"round":"string","at":"datetime","note":"string"}},"offer":{"required":[],"fields":{"note":"string"}},"rejected":{"required":[],"fields":{"note":"string"}},"withdrawn":{"required":[],"fields":{"note":"string"}}}}',
 '140eb82cf26d5711553a900070453acfb70945d22b96c3fd7af15447be0287e5', '2026-09-14T00:00:00.000000Z', 1);

-- 有效事件：每条业务根事件沿纠错链走到末端；末端是 retract 则无有效事实；末端是 replace 则取替代内容与替代发生时间。
-- 读侧不设深度截断：写侧只允许纠正当前末端、同流同主体、单后继（部分唯一索引），因此链无环且有限。depth 仅用于诊断。
CREATE VIEW v_effective_events AS
WITH RECURSIVE chain(root_id, cur_id, depth) AS (
  SELECT event_id, event_id, 0 FROM events WHERE corrected_event_id IS NULL
  UNION ALL
  SELECT c.root_id, e.event_id, c.depth + 1
  FROM chain c JOIN events e ON e.corrected_event_id = c.cur_id
),
tails AS (
  SELECT root_id, cur_id AS tail_id, depth FROM chain c
  WHERE NOT EXISTS (SELECT 1 FROM events x WHERE x.corrected_event_id = c.cur_id)
)
SELECT
  r.event_id            AS root_id,
  t.tail_id             AS current_id,
  t.depth               AS chain_depth,
  r.stream, r.stream_revision, r.subject_kind, r.subject_id, r.origin,
  CASE WHEN t.tail_id = r.event_id THEN r.type
       ELSE json_extract(tl.payload_json, '$.original_type') END            AS type,
  CASE WHEN t.tail_id = r.event_id THEN r.occurred_at
       ELSE json_extract(tl.payload_json, '$.replacement_occurred_at') END  AS occurred_at,
  CASE WHEN t.tail_id = r.event_id THEN r.payload_json
       ELSE json_extract(tl.payload_json, '$.replacement_payload') END      AS payload_json,
  tl.recorded_at        AS current_recorded_at,
  r.recorded_at         AS root_recorded_at,
  (t.tail_id <> r.event_id) AS corrected
FROM tails t
JOIN events r  ON r.event_id  = t.root_id
JOIN events tl ON tl.event_id = t.tail_id
WHERE r.type <> 'corrected'
  AND (t.tail_id = r.event_id OR json_extract(tl.payload_json, '$.op') = 'replace');

-- 每个岗位选中的一次投递及派生状态。选择：最近有效 applied（发生时间降序、application_id 升序）。
-- 状态：该投递全部有效事件按 (occurred_at DESC, current_recorded_at DESC, root_id DESC) 的第一条的类型。
-- followup_due：状态仍为 applied 且距投递发生时间 >= 72 小时（固定 as_of）。
CREATE VIEW v_job_application AS
WITH applied AS (
  SELECT a.job_id, a.application_id, ee.occurred_at AS applied_at
  FROM applications a
  JOIN v_effective_events ee
    ON ee.stream = 'applications' AND ee.subject_kind = 'application'
   AND ee.subject_id = a.application_id AND ee.type = 'applied'
),
chosen AS (
  SELECT job_id, application_id, applied_at,
         row_number() OVER (PARTITION BY job_id ORDER BY applied_at DESC, application_id ASC) AS rn
  FROM applied
),
last_ev AS (
  SELECT ee.subject_id AS application_id, ee.type,
         row_number() OVER (PARTITION BY ee.subject_id
                            ORDER BY ee.occurred_at DESC, ee.current_recorded_at DESC, ee.root_id DESC) AS rn
  FROM v_effective_events ee
  WHERE ee.stream = 'applications' AND ee.subject_kind = 'application'
)
SELECT c.job_id, c.application_id, c.applied_at,
       l.type AS application_state,
       CASE WHEN l.type = 'applied'
             AND (julianday(wmj_as_of()) - julianday(c.applied_at)) >= 3.0 THEN 1 ELSE 0 END AS followup_due
FROM chosen c
JOIN last_ev l ON l.application_id = c.application_id AND l.rn = 1
WHERE c.rn = 1;
DROP VIEW v_jobs;
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
  mr.match_run_id                                 AS match_run_id,
  mr.dir                                          AS dir,
  CASE WHEN mr.job_id IS NULL THEN 'missing'
       WHEN mr.fact_revision = s.content_hash
        AND mr.profile_revision IS NOT NULL
        AND wmj_profile_revision() IS NOT NULL
        AND mr.profile_revision = wmj_profile_revision() THEN 'current'
       ELSE 'stale' END                           AS match_state,
  mr.rule_score                                   AS rule_score,
  COALESCE(adj.delta, 0.0)                        AS score_adjustment,
  CASE WHEN mr.rule_score IS NULL THEN NULL ELSE mr.rule_score + COALESCE(adj.delta, 0.0) END AS score,
  CASE WHEN mr.rule_score IS NULL THEN NULL ELSE COALESCE(
       (SELECT t.key FROM json_each(json_extract(cr.config_json, '$.tiers')) t
         WHERE (mr.rule_score + COALESCE(adj.delta, 0.0)) >= t.value ORDER BY t.value DESC LIMIT 1),
       json_extract(cr.config_json, '$.fallback_tier')) END AS tier,
  CASE WHEN mr.rule_score IS NOT NULL AND adj.for_run = cr.run_id
       THEN json_insert(COALESCE(mr.reasons_json, '[]'), '$[#]',
              json_object('rule_id', 'user-adjustment', 'delta', adj.delta,
                          'reason', adj.reason, 'source', 'user', 'match_run_id', cr.run_id))
       ELSE COALESCE(mr.reasons_json, '[]') END AS reasons_json,
  mr.excluded                                     AS excluded,
  COALESCE(mr.exclusion_reasons_json, '[]')       AS exclusion_reasons_json,
  COALESCE(mr.unknowns_json, json_extract(s.fact_json, '$.unknowns'), '[]') AS unknowns_json,
  COALESCE(pu.priority, pa.priority)              AS priority,
  NULL AS current_bundle_id, NULL AS report_id, 'none' AS report_state,
  ja.application_id, ja.application_state, COALESCE(ja.followup_due, 0) AS followup_due
FROM jobs j
LEFT JOIN sightings s ON s.observation_id = j.current_sighting_id
LEFT JOIN companies c ON c.company_id = j.company_id
LEFT JOIN (SELECT run_id, config_json FROM runs WHERE kind = 'match' AND status = 'ok'
           ORDER BY started_at DESC, rowid DESC LIMIT 1) cr ON 1 = 1
LEFT JOIN match_results mr ON mr.match_run_id = cr.run_id AND mr.job_id = j.job_id
LEFT JOIN (SELECT job_id, json_extract(value_json, '$.delta') AS delta, json_extract(value_json, '$.match_run_id') AS for_run,
                  json_extract(value_json, '$.reason') AS reason
           FROM job_attrs WHERE key = 'score_adjustment' AND source = 'user') adj
       ON adj.job_id = j.job_id AND adj.for_run = cr.run_id
LEFT JOIN (SELECT job_id, json_extract(value_json, '$') AS priority FROM job_attrs WHERE key = 'priority' AND source = 'user') pu ON pu.job_id = j.job_id
LEFT JOIN (SELECT job_id, json_extract(value_json, '$') AS priority FROM job_attrs WHERE key = 'priority' AND source = 'agent') pa ON pa.job_id = j.job_id
LEFT JOIN v_job_application ja ON ja.job_id = j.job_id;
