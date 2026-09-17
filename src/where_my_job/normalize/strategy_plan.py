# src/where_my_job/normalize/strategy_plan.py
"""strategy.json 的唯一展开器（纯函数）。逐 关键词×城市×过滤组合×页 懒生成，按
(keyword, city_code, sorted(filters), page) 去重；去重后第一次超过上限立即报错，不先分配完整笛卡尔积。
validate.semantic.strategy、service.match 与子计划 05 的 service.scan_plan（re-export）共用。"""
from __future__ import annotations
import itertools
from dataclasses import dataclass, field
from typing import Iterator
from ..config.search_codes import UnknownCode, city_code, city_name, compile_filter, display_label, FILTER_TABLES
from ..errors import ErrorItem, InvalidInput

DEFAULT_PAGES = 1
DEFAULT_MAX_PAGES_PER_RUN = 20
HARD_MAX_PAGES = 80

class PlanError(InvalidInput):
    """展开失败。是 InvalidInput 子类：CLI 直接得到 SEMANTIC_INVALID / 退出 1，
    validate.semantic.strategy 仍按 PlanError 捕获并转成 Issue（path/message 由 WmjError 提供）。"""
    def __init__(self, path: str, message: str):
        super().__init__([ErrorItem("SEMANTIC_INVALID", message, path)])

class PlanLimitExceeded(PlanError):
    def __init__(self, seen: int, cap: int, raw_upper_bound: int):
        super().__init__("$.searches", f"展开后至少 {seen} 个不同动作，超过本 run 上限 {cap}（硬上限 {HARD_MAX_PAGES}；未去重计划 {raw_upper_bound}）")
        self.seen, self.cap, self.raw_upper_bound = seen, cap, raw_upper_bound

@dataclass(frozen=True)
class PlanTask:
    search_index: int
    keyword: str
    city_name: str
    city_code: str
    filters: dict = field(default_factory=dict)        # 参数 -> 规范码
    filter_labels: dict = field(default_factory=dict)  # 参数 -> 人可读文案（405 显示 10–20K）
    page: int = 1

    @property
    def city(self) -> str:
        """子计划 05 dry-run 输出使用的城市显示名。"""
        return self.city_name

    @property
    def task_key(self) -> str:
        """与去重身份一一对应的稳定键；子计划 05 用作 run_tasks.task_key。"""
        fl = ",".join(f"{k}={v}" for k, v in sorted(self.filters.items()))
        return f"{self.keyword}|{self.city_code}|{fl}|p{self.page}"

@dataclass(frozen=True)
class Plan:
    tasks: tuple[PlanTask, ...]
    cap: int
    raw_upper_bound: int
    name: str = ""
    pause: tuple[float, float] = (12.0, 22.0)

    @property
    def actions(self) -> int:
        """受控动作数 = 去重后的页数。"""
        return len(self.tasks)

    def estimated_seconds(self) -> list[int]:
        """仅动作间等待的下界与上界（秒），不含页面加载耗时。"""
        gaps = max(self.actions - 1, 0)
        return [int(gaps * self.pause[0]), int(gaps * self.pause[1])]

def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]

def _compile_search(i: int, s: dict) -> tuple[list[str], list[tuple[str, str]], list[tuple[str, list[str]]], int]:
    keywords = list(dict.fromkeys(k.strip() for k in s["keywords"]))
    cities: list[tuple[str, str]] = []
    for j, c in enumerate(s["cities"]):
        try:
            code = city_code(c)
        except UnknownCode as e:
            raise PlanError(f"$.searches[{i}].cities[{j}]", str(e))
        if all(code != existing for existing, _ in cities):
            cities.append((code, city_name(code)))
    filters: list[tuple[str, list[str]]] = []
    for param in sorted((s.get("boss_filters") or {})):
        if param not in FILTER_TABLES:
            raise PlanError(f"$.searches[{i}].boss_filters.{param}", f"不支持的筛选参数: {param}")
        raw = s["boss_filters"][param]
        values = _as_list(raw)
        codes: list[str] = []
        for j, v in enumerate(values):
            path = f"$.searches[{i}].boss_filters.{param}" + (f"[{j}]" if isinstance(raw, list) else "")
            try:
                code = compile_filter(param, v).code
            except UnknownCode as e:
                raise PlanError(path, str(e))
            if code not in codes:
                codes.append(code)
        filters.append((param, codes))
    pages = s.get("pages", DEFAULT_PAGES)
    return keywords, cities, filters, pages

def iter_tasks(strategy: dict) -> Iterator[PlanTask]:
    """懒生成（未去重）；编译错误在遇到对应搜索时抛出。"""
    for i, s in enumerate(strategy["searches"]):
        keywords, cities, filters, pages = _compile_search(i, s)
        params = [p for p, _ in filters]
        for kw in keywords:
            for code, name in cities:
                for combo in itertools.product(*[codes for _, codes in filters]):
                    chosen = dict(zip(params, combo))
                    labels = {p: display_label(p, c) for p, c in chosen.items()}
                    for page in range(1, pages + 1):
                        yield PlanTask(i, kw, name, code, chosen, labels, page)

def _raw_upper_bound(strategy: dict) -> int:
    total = 0
    for s in strategy["searches"]:
        combos = 1
        for v in (s.get("boss_filters") or {}).values():
            combos *= len(_as_list(v))
        total += len(s["keywords"]) * len(s["cities"]) * combos * s.get("pages", DEFAULT_PAGES)
    return total

def expand_plan(strategy: dict) -> Plan:
    budget = strategy.get("budget") or {}
    cap = min(budget.get("max_pages_per_run", DEFAULT_MAX_PAGES_PER_RUN), HARD_MAX_PAGES)
    seen: set[tuple] = set()
    tasks: list[PlanTask] = []
    for t in iter_tasks(strategy):
        identity = (t.keyword, t.city_code, tuple(sorted(t.filters.items())), t.page)
        if identity in seen:
            continue
        seen.add(identity)
        if len(seen) > cap:
            raise PlanLimitExceeded(len(seen), cap, _raw_upper_bound(strategy))
        tasks.append(t)
    lo, hi = budget.get("pause_between_actions_sec", [12, 22])
    return Plan(tuple(tasks), cap, _raw_upper_bound(strategy),
                name=str(strategy.get("name", "")), pause=(float(lo), float(hi)))
