from where_my_job.normalize.salary import parse_salary

def test_month_range_with_pay_months():
    s = parse_salary("15-25K·14薪")
    assert (s.lo, s.hi, s.currency, s.period, s.pay_months) == (15.0, 25.0, "CNY", "month", 14)

def test_month_range_without_months_keeps_none():
    s = parse_salary("8-12K")
    assert (s.lo, s.hi, s.period, s.pay_months) == (8.0, 12.0, "month", None)

def test_daily_hourly_and_yuan_month():
    d = parse_salary("300-400元/天"); h = parse_salary("50-80元/时"); m = parse_salary("6000-8000元/月")
    assert (d.lo, d.hi, d.period) == (300.0, 400.0, "day")
    assert (h.lo, h.hi, h.period) == (50.0, 80.0, "hour")
    assert (m.lo, m.hi, m.period) == (6.0, 8.0, "month")

def test_decimal_negotiable_and_empty():
    assert parse_salary("9.5-12K").lo == 9.5
    n = parse_salary("面议")
    assert (n.lo, n.hi, n.period, n.text) == (None, None, None, "面议")
    g = parse_salary("")
    assert g.text is None and g.lo is None

def test_invalid_ranges_become_unknown_but_keep_text():
    for text in ("20-10K", "10-20K·0薪", "9" * 400 + "-" + "9" * 401 + "K"):
        s = parse_salary(text)
        assert (s.lo, s.hi, s.period, s.pay_months, s.currency) == (None, None, None, None, None)
        assert s.text == text
