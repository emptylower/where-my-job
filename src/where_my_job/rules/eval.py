# src/where_my_job/rules/eval.py
"""scoring.json 编译与单岗位求值。纯函数；不访问 store。"""
from __future__ import annotations
import json
import math
import re
from dataclasses import dataclass
from ..normalize.fact import Fact
from .ast import parse, evaluate, matched_facts, RuleParseError, Leaf, Node
from .fields import FIELDS, get_value
from .skills import count_hits
from . import limits

CAMPUS_EXP = frozenset({"在校生", "应届生", "在校/应届"})
RESERVED_RULE_IDS = frozenset({"base", "experience-allowlist", "campus-policy", "user-adjustment"})

class ScoringCompileError(ValueError):
    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path, self.message = path, message

@dataclass(frozen=True)
class ScoreRule:
    id: str
    reason: str
    when: "Leaf | Node | None"
    add: float | None
    group: str | None
    skills_hit: dict | None          # {"field","categories","per_category","cap","flags_i"}

@dataclass(frozen=True)
class DirScoring:
    base: float
    base_reason: str
    rules: tuple[ScoreRule, ...]
    groups: dict[str, tuple[float | None, float | None]]

@dataclass(frozen=True)
class CompiledScoring:
    profile_revision: str
    campus_policy: str
    classify: tuple[tuple[str | None, "Leaf | Node"], ...]
    exclude: tuple[tuple[str, "Leaf | Node", str], ...]
    score: dict[str, DirScoring]
    global_rules: tuple[ScoreRule, ...]
    tiers: tuple[tuple[str, float], ...]      # 降序
    fallback_tier: str
    experience_allowlist: tuple[str, ...] | None

@dataclass
class JobResult:
    dir: str | None
    classified: bool
    excluded: bool
    exclusion_reasons: list[dict]
    rule_score: float | None
    tier: str | None
    reasons: list[dict]
    unknowns: list[str]

def _num(value, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoringCompileError(path, "需要有限数值，不接受字符串或布尔值")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ScoringCompileError(path, "数值超出有限浮点范围")
    if not math.isfinite(number):
        raise ScoringCompileError(path, "需要有限数值")
    return number

def _rule(obj: dict, path: str, seen: set[str]) -> ScoreRule:
    rid = obj.get("id")
    if not isinstance(rid, str) or rid in RESERVED_RULE_IDS or rid.startswith("group:"):
        raise ScoringCompileError(f"{path}.id", f"规则 id 为保留名或非字符串: {rid!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", rid):
        raise ScoringCompileError(f"{path}.id", "规则 id 须为小写 ASCII 标识符")
    if rid in seen:
        raise ScoringCompileError(f"{path}.id", f"规则 id 重复: {rid}")
    seen.add(rid)
    reason = obj.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ScoringCompileError(f"{path}.reason", "需要非空理由")
    if "skills_hit" in obj:
        sh = obj["skills_hit"]
        if "when" in obj or "add" in obj:
            raise ScoringCompileError(path, "skills_hit 规则不能同时有 when/add")
        cats = sh.get("categories")
        if not isinstance(cats, dict) or not cats or not all(isinstance(k, str) and isinstance(v, str) for k, v in cats.items()):
            raise ScoringCompileError(f"{path}.skills_hit.categories", "需要 {类别: 正则} 非空对象")
        for k, v in cats.items():
            if len(v) > limits.MAX_PATTERN_LEN:
                raise ScoringCompileError(f"{path}.skills_hit.categories.{k}", "模式过长")
            try:
                re.compile(v)
            except re.error as e:
                raise ScoringCompileError(f"{path}.skills_hit.categories.{k}", f"正则无效: {e}")
        fld = sh.get("field", "title_skills")
        if FIELDS.get(fld) != "text":
            raise ScoringCompileError(f"{path}.skills_hit.field", "需要已注册的文本字段")
        per = _num(sh.get("per_category", 1), f"{path}.skills_hit.per_category")
        cap = _num(sh.get("cap", 6), f"{path}.skills_hit.cap")
        if per < 0:
            raise ScoringCompileError(f"{path}.skills_hit.per_category", "不能为负")
        if cap < 0:
            raise ScoringCompileError(f"{path}.skills_hit.cap", "不能为负")
        return ScoreRule(rid, reason, None, None, obj.get("group"),
                         {"field": fld, "categories": dict(cats), "per_category": per, "cap": cap,
                          "flags_i": sh.get("flags", "") == "i"})
    if "when" not in obj:
        raise ScoringCompileError(f"{path}.when", "缺少 when")
    try:
        when = parse(obj["when"], f"{path}.when")
    except RuleParseError as e:
        raise ScoringCompileError(e.path, e.message)
    add = _num(obj.get("add"), f"{path}.add")
    grp = obj.get("group")
    if grp is not None and not isinstance(grp, str):
        raise ScoringCompileError(f"{path}.group", "group 须为字符串")
    return ScoreRule(rid, reason, when, add, grp, None)

def compile_scoring(cfg: dict) -> CompiledScoring:
    try:
        size = len(json.dumps(cfg, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except ValueError:
        raise ScoringCompileError("$", "配置含非有限数值")
    if size > limits.MAX_CONFIG_BYTES:
        raise ScoringCompileError("$", f"配置 {size} 字节，超过 {limits.MAX_CONFIG_BYTES} 字节")
    total = len(cfg.get("classify", [])) + len(cfg.get("exclude", [])) + len(cfg.get("global", [])) \
        + sum(len(d.get("rules", [])) for d in cfg.get("score", {}).values())
    if total > limits.MAX_RULES_TOTAL:
        raise ScoringCompileError("$", f"规则总数 {total} 超过 {limits.MAX_RULES_TOTAL}")
    seen: set[str] = set()
    classify = []
    for i, c in enumerate(cfg.get("classify", [])):
        d = c.get("dir")
        if d is not None and (not isinstance(d, str) or not d):
            raise ScoringCompileError(f"$.classify[{i}].dir", "dir 须为非空字符串或 null")
        try:
            classify.append((d, parse(c["when"], f"$.classify[{i}].when")))
        except RuleParseError as e:
            raise ScoringCompileError(e.path, e.message)
    exclude = []
    for i, x in enumerate(cfg.get("exclude", [])):
        r = _rule({**x, "add": 0}, f"$.exclude[{i}]", seen)
        exclude.append((r.id, r.when, r.reason))
    score: dict[str, DirScoring] = {}
    for dname, d in cfg.get("score", {}).items():
        base = _num(d.get("base"), f"$.score.{dname}.base")
        base_reason = d.get("base_reason")
        if not isinstance(base_reason, str) or not base_reason.strip():
            raise ScoringCompileError(f"$.score.{dname}.base_reason", "需要非空的基分理由")
        rules = tuple(_rule(r, f"$.score.{dname}.rules[{i}]", seen) for i, r in enumerate(d.get("rules", [])))
        groups: dict[str, tuple[float | None, float | None]] = {}
        for g, bounds in (d.get("groups") or {}).items():
            lo = _num(bounds["min"], f"$.score.{dname}.groups.{g}.min") if "min" in bounds else None
            hi = _num(bounds["max"], f"$.score.{dname}.groups.{g}.max") if "max" in bounds else None
            if lo is not None and hi is not None and lo > hi:
                raise ScoringCompileError(f"$.score.{dname}.groups.{g}", "min 不能大于 max")
            groups[g] = (lo, hi)
        for r in rules:
            if r.group and r.group not in groups:
                raise ScoringCompileError(f"$.score.{dname}.rules", f"规则 {r.id} 引用未定义的 group {r.group}")
        score[dname] = DirScoring(base, base_reason.strip(), rules, groups)
    for d, _ in classify:
        if d is not None and d not in score:
            raise ScoringCompileError("$.score", f"方向 {d} 没有计分配置")
    glob = []
    for i, r in enumerate(cfg.get("global", [])):
        if "group" in r:
            raise ScoringCompileError(f"$.global[{i}].group", "global 规则不支持 group；请放进方向内的计分组")
        glob.append(_rule(r, f"$.global[{i}]", seen))
    tiers_cfg = cfg.get("tiers") or {}
    tiers = tuple((k, _num(v, f"$.tiers.{k}")) for k, v in tiers_cfg.items())
    vals = [v for _, v in tiers]
    if not tiers or vals != sorted(vals, reverse=True) or len(set(vals)) != len(vals):
        raise ScoringCompileError("$.tiers", "tiers 必须按阈值严格降序给出")
    fb = cfg.get("fallback_tier")
    if not isinstance(fb, str) or fb in tiers_cfg:
        raise ScoringCompileError("$.fallback_tier", "需要一个不与 tiers 重名的字符串")
    allow = cfg.get("experience_allowlist")
    return CompiledScoring(str(cfg["profile_revision"]), cfg.get("campus_policy", "auto"), tuple(classify),
                           tuple(exclude), score, tuple(glob), tiers, fb, tuple(allow) if allow else None)

def evaluate_job(sc: CompiledScoring, fact: Fact, *, campus_exclude: bool = False) -> JobResult:
    unknowns = list(fact.unknowns)
    def note_unknown(node):
        for fname, v in matched_facts(node, fact).items():
            if v is None and fname not in unknowns:
                unknowns.append(fname)
    # 分类
    dir_, classified = None, False
    for d, when in sc.classify:
        r = evaluate(when, fact)
        if r is None: note_unknown(when)
        if r is True:
            dir_, classified = d, True
            break
    # 排除（只有 True 触发）
    excl_reasons: list[dict] = []
    for rid, when, reason in sc.exclude:
        r = evaluate(when, fact)
        if r is None: note_unknown(when)
        if r is True:
            excl_reasons.append({"rule_id": rid, "reason": reason, "facts": matched_facts(when, fact)})
    # 经验白名单：校园档交给 campus_policy；未知经验记 unknown、不硬排除
    if sc.experience_allowlist:
        if fact.exp is None:
            if "exp" not in unknowns:
                unknowns.append("exp")
        elif fact.exp not in CAMPUS_EXP and fact.exp not in sc.experience_allowlist:
            excl_reasons.append({"rule_id": "experience-allowlist",
                                 "reason": "不在本次允许的经验范围内",
                                 "facts": {"exp": fact.exp, "allowed": list(sc.experience_allowlist)}})
    if campus_exclude and fact.exp in CAMPUS_EXP:
        excl_reasons.append({"rule_id": "campus-policy", "reason": "校园岗位按经验范围推导为排除", "facts": {"exp": fact.exp}})
    excluded = bool(excl_reasons)
    if dir_ is None:
        return JobResult(None, classified, excluded, excl_reasons, None, None, [], unknowns)
    # 计分
    ds = sc.score[dir_]
    reasons: list[dict] = [{"rule_id": "base", "delta": ds.base, "reason": ds.base_reason}]
    group_raw: dict[str, list[dict]] = {}
    def apply(rule: ScoreRule):
        if rule.skills_hit:
            text = get_value(fact, rule.skills_hit["field"])
            hits, n = count_hits(text, rule.skills_hit["categories"], flags_i=rule.skills_hit["flags_i"])
            if n == 0:
                if text is None and rule.skills_hit["field"] not in unknowns:
                    unknowns.append(rule.skills_hit["field"])
                return
            delta = min(n * rule.skills_hit["per_category"], rule.skills_hit["cap"])
            entry = {"rule_id": rule.id, "delta": delta, "reason": rule.reason, "hits": hits}
        else:
            r = evaluate(rule.when, fact)
            if r is None:
                note_unknown(rule.when)
                return
            if r is not True:
                return
            entry = {"rule_id": rule.id, "delta": rule.add, "reason": rule.reason, "facts": matched_facts(rule.when, fact)}
        if rule.group:
            group_raw.setdefault(rule.group, []).append(entry)
        else:
            reasons.append(entry)
    for rule in ds.rules:
        apply(rule)
    for g, (lo, hi) in ds.groups.items():          # 未命中组 raw=0 也应用上下界
        entries = group_raw.get(g, [])
        raw = sum(e["delta"] for e in entries)
        capped = raw
        if hi is not None: capped = min(capped, hi)
        if lo is not None: capped = max(capped, lo)
        reasons.append({"rule_id": f"group:{g}", "delta": capped, "raw": raw, "bounds": {"min": lo, "max": hi},
                        "reason": f"计分组 {g}：成员合计 {raw:g}，按上下界计 {capped:g}", "members": entries})
    for rule in sc.global_rules:
        apply(rule)
    total = sum(c["delta"] for c in reasons)
    tier = next((name for name, th in sc.tiers if total >= th), sc.fallback_tier)
    return JobResult(dir_, True, excluded, excl_reasons, total, tier, reasons, unknowns)

def tier_for(sc: CompiledScoring, score: float) -> str:
    return next((name for name, th in sc.tiers if score >= th), sc.fallback_tier)
