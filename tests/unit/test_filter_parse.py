# tests/unit/test_filter_parse.py
import pytest
from where_my_job.errors import InvalidInput
from where_my_job.service.jobs import _parse_filters

def test_longest_operator_wins():
    assert _parse_filters(["hit_count>=2"]) == {"hit_count>=": "2"}
    assert _parse_filters(["exp!=3-5年"]) == {"exp!=": "3-5年"}
    assert _parse_filters(["salary_lo<10", "salary_hi>20"]) == {"salary_lo<": "10", "salary_hi>": "20"}
    assert _parse_filters(["city=合肥"]) == {"city": "合肥"}
    assert _parse_filters(["title~=产品"]) == {"title~": "产品"}
    assert _parse_filters(["title~a=b"]) == {"title~": "a=b"}

@pytest.mark.parametrize("items", [["no-operator"], ["City=x"], ["=x"], ["city=a", "city=b"], ["title~x", "title~=y"]])
def test_bad_or_duplicate_filters_rejected(items):
    with pytest.raises(InvalidInput):
        _parse_filters(items)
