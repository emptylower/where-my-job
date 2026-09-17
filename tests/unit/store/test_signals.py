# tests/unit/store/test_signals.py
from where_my_job.store.signals import observation_span, count_ratio, list_detail_diff, up_date_raw

BANNED = ("发布于", "发布日期为", "持续招聘", "持续可见", "仍有编制", "养鱼")

def test_observation_span_wording_as_of_and_none():
    s = observation_span(first="2026-09-01T00:00:00.000000Z", last="2026-09-14T00:00:00.000000Z",
                         hits=3, runs=2, as_of="2026-09-14T12:00:00.000000Z")
    assert s["days"] == 13 and s["hits"] == 3 and s["runs"] == 2 and s["as_of"] == "2026-09-14T12:00:00.000000Z"
    assert "观察跨度" in s["statement"] and "无法确认发布日期" in s["statement"]
    assert not any(b in s["statement"] for b in BANNED)
    none = observation_span(first=None, last=None, hits=0, runs=0, as_of="2026-09-14T12:00:00.000000Z")
    assert none["days"] is None and not any(b in none["statement"] for b in BANNED)

def test_count_ratio_unknown_on_missing_zero_or_non_int_and_precision():
    assert count_ratio(boss_count=3, job_count=12)["ratio"] == 0.25
    assert count_ratio(boss_count=3, job_count=22)["ratio"] == 0.1364
    assert count_ratio(boss_count=None, job_count=12)["ratio"] == "unknown"
    assert count_ratio(boss_count=3, job_count=0)["ratio"] == "unknown"
    assert count_ratio(boss_count="3", job_count=12)["ratio"] == "unknown"
    assert count_ratio(boss_count=True, job_count=12)["ratio"] == "unknown"
    r = count_ratio(boss_count=1, job_count=22, boss_count_raw="招聘者 1", job_count_raw="在招职位 22")
    assert r["boss_count_raw"] == "招聘者 1" and r["job_count_raw"] == "在招职位 22"
    assert not any(b in r["statement"] for b in BANNED)

def test_list_detail_diff_reports_conflicts_only():
    fact = {"salary_text": "15-25K·14薪", "exp": "1-3年", "degree": "本科"}
    detail = {"detail_salary_text": "15-25K·14薪", "detail_exp": "3-5年", "detail_degree": "本科"}
    assert list_detail_diff(fact, detail) == [{"field": "exp", "list": "1-3年", "detail": "3-5年"}]
    assert list_detail_diff(fact, {}) == []

def test_up_date_reads_normalized_key_and_shows_raw():
    u = up_date_raw({"ld_json_upDate": "2026-08-20 10:12:00", "ld_upDate_raw": "2026-08-20 10:12:00"})
    assert u["value"] == "2026-08-20 10:12:00" and u["raw"] == "2026-08-20 10:12:00"
    assert "无法确认发布日期" in u["statement"] and not any(b in u["statement"] for b in BANNED)
    assert up_date_raw({"upDate": "x"})["value"] is None
