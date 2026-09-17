# tests/unit/store/test_v_jobs_report_view.py
from pathlib import Path
from tests.helpers.evidence_seed import seed_job, seed_detail
from where_my_job.store import db, runs, bundles, views

MIGRATIONS = Path(__file__).resolve().parents[3] / "src" / "where_my_job" / "store" / "migrations"
REPORT_COLUMNS = {"current_bundle_id", "report_id", "report_state"}

def test_v_jobs_columns_and_order_after_0004(conn):
    cols = [d[0] for d in conn.execute("select * from v_jobs limit 0").description]
    assert cols == ["view_schema_version"] + list(views.V_JOBS_COLUMNS)
    assert len(cols) == 41

def test_0004_only_changes_report_columns(conn, clock):
    db.bind_profile_revision(conn, "example-minimal-v1")
    seed_job(conn, clock, "boss:SYN0001aaaa", company_id="boss:SYNCO1")
    seed_job(conn, clock, "boss:SYN0002bbbb", company_id="boss:SYNCO2", fixture_index=1)
    with db.write_tx(conn):
        conn.execute("""insert into job_attrs(job_id, key, value_json, source, updated_at) values
                        ('boss:SYN0001aaaa', 'priority', '"focus"', 'user', '2026-09-14T12:00:00.000000Z'),
                        ('boss:SYN0001aaaa', 'priority', '"later"', 'agent', '2026-09-14T12:00:00.000000Z')""")
    d = seed_detail(conn, clock, "boss:SYN0001aaaa")
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="deepdive", config={}, planned=1)
        bundles.create(conn, clock, job_id="boss:SYN0001aaaa", run_id=run_id, evidence_ids=[d],
                       acquisition_state="complete", unknowns=[])
    sql = (MIGRATIONS / "0003_streams.sql").read_text(encoding="utf-8")
    marker = "CREATE VIEW v_jobs AS"
    previous = marker + "\n" + sql.split(marker, 1)[1].strip().rstrip(";")
    conn.execute(previous.replace(marker, "CREATE TEMP VIEW v_jobs_0003 AS", 1))
    new_rows = {r["job_id"]: dict(r) for r in conn.execute("select * from v_jobs")}
    old_rows = {r["job_id"]: dict(r) for r in conn.execute("select * from v_jobs_0003")}
    assert new_rows.keys() == old_rows.keys() == {"boss:SYN0001aaaa", "boss:SYN0002bbbb"}
    for job_id, row in new_rows.items():
        for column, value in row.items():
            if column not in REPORT_COLUMNS:
                assert value == old_rows[job_id][column], (job_id, column)
    assert new_rows["boss:SYN0001aaaa"]["report_state"] == "analysis_pending"
    assert old_rows["boss:SYN0001aaaa"]["report_state"] == "none"
    assert new_rows["boss:SYN0002bbbb"]["report_state"] == "none"
    assert new_rows["boss:SYN0001aaaa"]["priority"] == "focus"
