from where_my_job.normalize.location import parse_location
from where_my_job.normalize.skills import split_list

def test_location_three_parts_and_blanks():
    assert parse_location("合肥·蜀山区·政务区") == ("合肥", "蜀山区")
    assert parse_location("合肥··") == ("合肥", None)
    assert parse_location("") == (None, None)

def test_split_list_dedup_preserve_order():
    assert split_list("AI产品 | Agent | AI产品 |  ") == ("AI产品", "Agent")
    assert split_list("") == () and split_list(None) == ()
