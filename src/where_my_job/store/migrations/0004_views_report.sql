
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
  cb.bundle_id AS current_bundle_id,
  ld.report_id AS report_id,
  CASE WHEN cb.bundle_id IS NULL AND ld.report_id IS NULL THEN 'none'
       WHEN ld.report_id IS NULL THEN 'analysis_pending'
       WHEN ld.bundle_id = cb.bundle_id
        AND cb.fact_sighting_id IS j.current_sighting_id
        AND wmj_profile_revision() IS NOT NULL
        AND ld.profile_revision = wmj_profile_revision() THEN 'complete'
       ELSE 'stale' END AS report_state,
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
LEFT JOIN v_job_application ja ON ja.job_id = j.job_id
LEFT JOIN (
  SELECT b.job_id, b.bundle_id, b.fact_sighting_id FROM evidence_bundles b
  WHERE b.bundle_id = (SELECT b2.bundle_id FROM evidence_bundles b2
    WHERE b2.job_id = b.job_id ORDER BY b2.created_at DESC, b2.bundle_version DESC, b2.rowid DESC LIMIT 1)
) cb ON cb.job_id = j.job_id
LEFT JOIN (
  SELECT d.job_id, d.report_id, d.bundle_id, d.profile_revision FROM deepdives d
  WHERE d.report_id = (SELECT d2.report_id FROM deepdives d2
    WHERE d2.job_id = d.job_id ORDER BY d2.created_at DESC, d2.rowid DESC LIMIT 1)
) ld ON ld.job_id = j.job_id;
