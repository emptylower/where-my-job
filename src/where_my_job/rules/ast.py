# src/where_my_job/rules/ast.py
"""条件树：{"all":[...]} | {"any":[...]} | {"not":{...}} | 叶子 {"field":F, <op>:V [, "flags":"i"]}
叶子算子：exists(bool) / match(regex, 文本) / eq / gte / lte / in(list)。
求值返回 True / False / None(unknown)。"""
from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import Any
from ..normalize.fact import Fact
from .fields import FIELDS, get_value
from . import limits

class RuleParseError(ValueError):
    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path, self.message = path, message

@dataclass(frozen=True)
class Leaf:
    field: str
    op: str
    value: Any
    regex: "re.Pattern[str] | None" = None

@dataclass(frozen=True)
class Node:
    kind: str            # all | any | not
    children: tuple      # tuple[Leaf | Node, ...]

LEAF_OPS = ("exists", "match", "eq", "gte", "lte", "in")

def _finite_number(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)

def parse(obj: Any, path: str = "$", depth: int = 1) -> "Leaf | Node":
    if depth > limits.MAX_DEPTH:
        raise RuleParseError(path, f"条件深度超过 {limits.MAX_DEPTH}")
    if not isinstance(obj, dict):
        raise RuleParseError(path, "条件必须是对象")
    keys = set(obj)
    if keys & {"all", "any"}:
        kind = "all" if "all" in keys else "any"
        if keys != {kind}:
            raise RuleParseError(path, f"{kind} 节点只能有 {kind} 一个键")
        items = obj[kind]
        if not isinstance(items, list) or not items:
            raise RuleParseError(f"{path}.{kind}", "需要非空数组")
        return Node(kind, tuple(parse(c, f"{path}.{kind}[{i}]", depth + 1) for i, c in enumerate(items)))
    if "not" in keys:
        if keys != {"not"}:
            raise RuleParseError(path, "not 节点只能有 not 一个键")
        return Node("not", (parse(obj["not"], f"{path}.not", depth + 1),))
    field = obj.get("field")
    if not isinstance(field, str) or field not in FIELDS:
        raise RuleParseError(f"{path}.field", f"字段未注册: {field!r}")
    ops = [k for k in LEAF_OPS if k in obj]
    if len(ops) != 1:
        raise RuleParseError(path, f"叶子必须恰有一个算子（{', '.join(LEAF_OPS)}）")
    op = ops[0]
    extra = keys - {"field", op, "flags"}
    if extra:
        raise RuleParseError(path, f"未知键 {sorted(extra)}")
    if "flags" in obj and op != "match":
        raise RuleParseError(f"{path}.flags", "flags 只能与 match 一起用")
    typ = FIELDS[field]
    val = obj[op]
    if op == "exists":
        if val is not True:
            raise RuleParseError(f"{path}.exists", "exists 只能是 true")
        return Leaf(field, op, True)
    if op == "match":
        if typ != "text":
            raise RuleParseError(f"{path}.match", f"match 只作用于文本字段，{field} 是 {typ}")
        if not isinstance(val, str) or not val:
            raise RuleParseError(f"{path}.match", "需要非空字符串")
        if len(val) > limits.MAX_PATTERN_LEN:
            raise RuleParseError(f"{path}.match", f"模式长度超过 {limits.MAX_PATTERN_LEN}")
        flags = obj.get("flags", "")
        if not isinstance(flags, str) or set(flags) - {"i"}:
            raise RuleParseError(f"{path}.flags", "只支持 flags=\"i\"")
        try:
            rx = re.compile(val, re.IGNORECASE if "i" in flags else 0)
        except re.error as e:
            raise RuleParseError(f"{path}.match", f"正则无效: {e}")
        return Leaf(field, op, val, rx)
    if typ == "list":
        raise RuleParseError(f"{path}.{op}", f"{field} 是列表字段，只能通过派生文本 match")
    if op in ("gte", "lte"):
        if typ not in ("num", "int") or not _finite_number(val):
            raise RuleParseError(f"{path}.{op}", f"{op} 需要数值字段与有限数值常量")
        return Leaf(field, op, float(val))
    if op == "eq":
        if typ == "text" and not isinstance(val, str):
            raise RuleParseError(f"{path}.eq", "文本字段需要字符串")
        if typ in ("num", "int") and not _finite_number(val):
            raise RuleParseError(f"{path}.eq", "数值字段需要有限数值")
        return Leaf(field, op, val)
    # in
    if not isinstance(val, list) or not val:
        raise RuleParseError(f"{path}.in", "需要非空数组")
    if typ == "text" and not all(isinstance(x, str) for x in val):
        raise RuleParseError(f"{path}.in", "文本字段的候选必须都是字符串")
    if typ in ("num", "int") and not all(_finite_number(x) for x in val):
        raise RuleParseError(f"{path}.in", "数值字段的候选必须都是有限数值")
    return Leaf(field, op, tuple(val))

def evaluate(node: "Leaf | Node", fact: Fact) -> bool | None:
    if isinstance(node, Leaf):
        v = get_value(fact, node.field)
        if node.op == "exists":
            return v is not None
        if v is None:
            return None
        if node.op == "match":
            text = v if len(v) <= limits.MAX_INPUT_TEXT else v[: limits.MAX_INPUT_TEXT]
            return node.regex.search(text) is not None
        if node.op == "eq":
            return v == node.value
        if node.op == "gte":
            return float(v) >= node.value
        if node.op == "lte":
            return float(v) <= node.value
        if node.op == "in":
            return v in node.value
        raise AssertionError(node.op)
    results = [evaluate(c, fact) for c in node.children]
    if node.kind == "not":
        r = results[0]
        return None if r is None else (not r)
    if node.kind == "all":
        if any(r is False for r in results): return False
        if any(r is None for r in results): return None
        return True
    if any(r is True for r in results): return True
    if any(r is None for r in results): return None
    return False

def matched_facts(node: "Leaf | Node", fact: Fact) -> dict[str, Any]:
    """命中时用于理由记录：叶子字段 -> 当时的值。"""
    out: dict[str, Any] = {}
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, Leaf):
            v = get_value(fact, n.field)
            out[n.field] = list(v) if isinstance(v, tuple) else v
        else:
            stack.extend(n.children)
    return out
