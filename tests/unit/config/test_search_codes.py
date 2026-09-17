# tests/unit/config/test_search_codes.py
import pytest
from where_my_job.config import search_codes as sc

def test_city_code_known_and_unknown():
    assert sc.city_code("合肥") == "101220100" and sc.city_code("101220100") == "101220100"
    assert sc.city_name("101200100") == "武汉"
    assert set(sc.CITY_CODES) == {"合肥", "上海", "北京", "深圳", "广州", "杭州", "武汉"}
    with pytest.raises(sc.UnknownCode):
        sc.city_code("火星")

def test_city_is_not_a_whitelist():
    """平台用中国天气网城市码（101 + 6 位），全国通用：裸码一律放行，内置七城只是便利名。
    我们不内置全国城市表——没有可信来源，编出来的码就是静默错值。"""
    assert sc.city_code("101270100") == "101270100"          # 内置里没有的城市，直接给码
    assert sc.city_name("101270100") == "101270100"          # 学不到名字就用码当显示名，不编
    assert sc.city_code("成都", {"成都": "101270100"}) == "101270100"
    assert sc.city_name("101270100", {"成都": "101270100"}) == "成都"
    for bad in ("火星", "10127010", "1012701000", "201270100", "101270a00", ""):
        with pytest.raises(sc.UnknownCode):
            sc.city_code(bad)
    assert "首发内置" not in str(pytest.raises(sc.UnknownCode, sc.city_code, "火星").value)

def test_compile_filter_label_and_code_same_value():
    assert sc.compile_filter("salary", "405") == sc.CompiledFilter(param="salary", code="405", label="10-20K")
    assert sc.compile_filter("salary", "10-20K").code == "405"
    assert sc.display_label("salary", "405") == "10–20K"
    assert sc.compile_filter("experience", "经验不限").code == "101"
    assert sc.compile_filter("experience", "101").label == "经验不限"
    assert sc.compile_filter("experience", "108").label == "在校生"
    with pytest.raises(sc.UnknownCode):
        sc.compile_filter("salary", "8-9K")
    with pytest.raises(sc.UnknownCode):
        sc.compile_filter("color", "red")
    with pytest.raises(sc.UnknownCode):
        sc.compile_filter("salary", 405)          # 数字 JSON 值不接受

def test_module_is_pure():
    import pathlib, re
    text = pathlib.Path(sc.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+[\w\.]*(adapter|service|store|policy|vendor)", text, re.M)
