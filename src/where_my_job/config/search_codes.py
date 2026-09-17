# src/where_my_job/config/search_codes.py
"""BOSS 服务端筛选码表与首发内置七城城市码（唯一来源，纯常量与纯函数）。
码值与上游固定版本（commit eb5a8e646d4e4bfc024cf53f2a5b543ad8d75edc）的 *_MAP 一致；子计划 05 的
adapter/codes.py 只 re-export 本模块，不另建码表。首发只内置下列七城；其余城市需用户提供码并记录来源。"""
from __future__ import annotations
from dataclasses import dataclass

class UnknownCode(ValueError):
    pass

CITY_CODES: dict[str, str] = {
    "合肥": "101220100", "上海": "101020100", "北京": "101010100", "深圳": "101280600",
    "广州": "101280100", "杭州": "101210100", "武汉": "101200100",
}

FILTER_TABLES: dict[str, dict[str, str]] = {   # 参数名 -> {人可读名: 码}
    "experience": {"不限": "0", "在校生": "108", "应届生": "102", "经验不限": "101", "1年以内": "103",
                   "1-3年": "104", "3-5年": "105", "5-10年": "106", "10年以上": "107"},
    "salary": {"不限": "0", "3K以下": "402", "3-5K": "403", "5-10K": "404", "10-20K": "405",
               "20-50K": "406", "50K以上": "407"},
    "degree": {"不限": "0", "初中及以下": "209", "中专/中技": "208", "高中": "206", "大专": "202",
               "本科": "203", "硕士": "204", "博士": "205"},
    "scale": {"0-20人": "301", "20-99人": "302", "100-499人": "303", "500-999人": "304",
              "1000-9999人": "305", "10000人以上": "306"},
    "stage": {"未融资": "801", "天使轮": "802", "A轮": "803", "B轮": "804", "C轮": "805",
              "D轮及以上": "806", "已上市": "807", "不需要融资": "808"},
    "industry": {"互联网": "1001", "电子商务": "1002", "金融": "1003", "游戏": "1004", "企业服务": "1005",
                 "教育培训": "1006", "社交网络": "1007", "医疗健康": "1008", "生活服务": "1009", "广告营销": "1010"},
}
# 展示文案：405 是 10–20K 区间，不是"至少 10K"
DISPLAY_OVERRIDES: dict[tuple[str, str], str] = {
    ("salary", "403"): "3–5K", ("salary", "404"): "5–10K", ("salary", "405"): "10–20K", ("salary", "406"): "20–50K",
}
EXPERIENCE_CAMPUS_CODES = frozenset({"101", "102", "108"})      # 经验不限 / 应届生 / 在校生
EXPERIENCE_YEAR_BAND_CODES = frozenset({"103", "104", "105", "106", "107"})

@dataclass(frozen=True)
class CompiledFilter:
    param: str
    code: str
    label: str

def city_code(name_or_code: str) -> str:
    if not isinstance(name_or_code, str):
        raise UnknownCode(f"城市必须是字符串: {name_or_code!r}")
    s = name_or_code.strip()
    if s in CITY_CODES:
        return CITY_CODES[s]
    if s.isdigit() and s in CITY_CODES.values():
        return s
    raise UnknownCode(f"未知城市或城市码: {s}（首发内置：{'、'.join(CITY_CODES)}）")

def city_name(code: str) -> str:
    for name, c in CITY_CODES.items():
        if c == code:
            return name
    raise UnknownCode(f"未知城市码: {code}")

def compile_filter(param: str, name_or_code: str) -> CompiledFilter:
    table = FILTER_TABLES.get(param)
    if table is None:
        raise UnknownCode(f"不支持的筛选参数: {param}（允许：{', '.join(FILTER_TABLES)}）")
    if not isinstance(name_or_code, str):
        raise UnknownCode(f"{param} 的取值必须是字符串: {name_or_code!r}")
    s = name_or_code.strip()
    if s in table:
        return CompiledFilter(param, table[s], s)
    rev = {v: k for k, v in table.items()}
    if s in rev:
        return CompiledFilter(param, s, rev[s])
    for (p, code), shown in DISPLAY_OVERRIDES.items():
        if p == param and shown == s:
            return CompiledFilter(param, code, rev[code])
    raise UnknownCode(f"{param} 的未知取值: {s}（允许：{', '.join(table)}）")

def display_label(param: str, code: str) -> str:
    if (param, code) in DISPLAY_OVERRIDES:
        return DISPLAY_OVERRIDES[(param, code)]
    rev = {v: k for k, v in FILTER_TABLES[param].items()}
    return rev[code]
