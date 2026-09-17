from where_my_job.adapter import codes
from where_my_job.config import search_codes

def test_codes_is_pure_reexport_of_config_search_codes():
    for name in ("UnknownCode", "CompiledFilter", "city_code", "compile_filter"):
        assert getattr(codes, name) is getattr(search_codes, name)

def test_codes_module_defines_no_tables_of_its_own():
    import inspect
    src = inspect.getsource(codes)
    assert "{" not in src.split('"""', 2)[-1]          # 没有任何字面量码表
