from where_my_job.normalize.tags import parse_tags

def test_exp_and_degree_split():
    assert parse_tags("1-3年 | 本科") == ("1-3年", "本科")
    assert parse_tags("在校/应届 | 硕士") == ("在校/应届", "硕士")
    assert parse_tags("经验不限 | 学历不限") == ("经验不限", "学历不限")

def test_normalizes_synonyms_and_unknown():
    assert parse_tags("研究生") == (None, "硕士")
    assert parse_tags("不限") == (None, "学历不限")
    assert parse_tags("") == (None, None)
    assert parse_tags(None) == (None, None)
    assert parse_tags("3年以内 | 本科", legacy=True) == ("3年以内", "本科")
    assert parse_tags("3年以内 | 本科") == (None, "本科")
