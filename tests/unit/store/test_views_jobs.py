# tests/unit/store/test_views_jobs.py
import pytest
from where_my_job.store import views
from where_my_job.errors import InvalidInput

def test_filter_whitelist_and_sort_on_empty_db(conn):
    rows, total, truncated = views.list_jobs(conn, views.JobQuery(filters={"city": "合肥"}, sort="last_seen_at", desc=True))
    assert rows == [] and total == 0 and truncated is False

def test_unknown_filter_key_rejected(conn):
    with pytest.raises(InvalidInput) as ei:
        views.list_jobs(conn, views.JobQuery(filters={"raw_json": "x"}))
    assert ei.value.items()[0].path == "$.filter.raw_json" and ei.value.code == "SEMANTIC_INVALID"

@pytest.mark.parametrize("value", ["abc", "nan", "inf", "-inf", "1e999"])
def test_numeric_filter_must_be_finite_number(conn, value):
    with pytest.raises(InvalidInput):
        views.list_jobs(conn, views.JobQuery(filters={"salary_lo>=": value}))

def test_text_operator_only_on_text_columns_and_page_size_capped(conn):
    with pytest.raises(InvalidInput):
        views.list_jobs(conn, views.JobQuery(filters={"hit_count~": "1"}))
    with pytest.raises(InvalidInput):
        views.list_jobs(conn, views.JobQuery(page_size=10_000))

def test_like_escape():
    assert views.like_pattern(r"100%_a\b") == "%100\\%\\_a\\\\b%"

def test_related_page_bounds(conn):
    with pytest.raises(InvalidInput):
        views.job_detail(conn, "boss:X", related_page_size=101)
    with pytest.raises(InvalidInput):
        views.job_detail(conn, "boss:X", related_page=0)
