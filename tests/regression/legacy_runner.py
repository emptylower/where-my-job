# tests/regression/legacy_runner.py
"""final_report.py + score_report.py 的纯函数复现。只用于私有回归与解释历史数据。"""
from __future__ import annotations
import json, re, sqlite3
from dataclasses import dataclass

CHIP_INDUSTRY = ("电子/半导体", "半导体", "集成电路", "芯片")
NET_INDUSTRY = ("互联网", "软件", "人工智能", "游戏", "电子商务", "数据服务", "企业服务", "智能硬件", "物联网",
                "信息安全", "社交", "在线教育", "消费电子", "通信")
EXP_KEEP_LEGACY = ("经验不限", "应届生", "在校生", "1年以内", "1-3年", "3年以内", "3年及以下")
EXP_KEEP_HANDOFF = EXP_KEEP_LEGACY + ("在校/应届",)
TIERS = [(90, "S"), (75, "A"), (60, "B"), (40, "C"), (0, "D")]

def parse_tags(tags: str):
    exp, deg = "未知", "未知"
    for seg in re.split(r"[|·]", tags or ""):
        s = seg.strip()
        if re.match(r"^(经验不限|应届生|在校生|在校/应届|\d+年以内|1-3年|3-5年|5-10年|10年以上|\d+年以上|3年及以下|3年以内)$", s):
            exp = s
        elif s in ("博士", "硕士", "研究生", "本科", "大专", "中专/中技", "高中", "初中及以下", "学历不限", "初中", "不限"):
            deg = s
    return exp, deg

def classify(job: dict):
    title = job.get("title") or ""; skills = job.get("skills") or ""; industry = job.get("company_industry") or ""
    blob = title + " " + skills
    chip_ctx = any(k in industry for k in CHIP_INDUSTRY) or re.search(r"芯片|IC\b|半导体|数字后端|模拟|晶圆|流片|FPGA|集成电路", blob, re.I)
    if chip_ctx:
        if re.search(r"验证|UVM|SystemVerilog|SV\b|DV\b|Emulation|仿真", blob, re.I): return "芯片验证"
        if re.search(r"后端|物理设计|布局布线|\bPR\b|版图|STA|时序|P&R|APR", blob, re.I) and not re.search(r"软件|Java|Python|Golang|PHP|Web|服务端", blob):
            return "数字后端"
        if re.search(r"测试|\bATE\b|量产|芯片测试|CP\b|FT\b", blob, re.I) and re.search(r"芯片|IC|半导体|晶圆|Wafer|ATE|SoC", blob, re.I):
            return "芯片测试"
        return None
    if re.search(r"全栈|全端|Full[- ]?Stack|前端.*后端", blob, re.I) and re.search(r"AI|人工智能|大模型|LLM|AIGC|机器学习|智能|GPT", blob, re.I):
        return "AI全栈"
    if re.search(r"产品经理|产品总监|产品负责人|PM\b", blob):
        if re.search(r"AI|人工智能|大模型|LLM|AIGC|智能", blob, re.I): return "AI产品经理"
        if any(k in industry for k in NET_INDUSTRY): return "互联网产品经理"
    return None

def parse_sal(s):
    m = re.match(r"(\d+)-(\d+)K", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

def score_job(j: dict):
    d = j["_dir"]; title = j.get("title") or ""; skills = j.get("skills") or ""; ind = j.get("company_industry") or ""
    scale = j.get("company_scale") or ""; b = f"{title} {skills} {ind}"; s = 0
    if d == "AI产品经理":
        s = 60
        if re.search(r"语义类AI|机器学习类AI|视觉类AI|语音类AI|Agent|AI机器人", b, re.I): s += 12
        if re.search(r"B端产品|中后台", b): s += 8
        if re.search(r"低代码|工具|效率", b): s += 6
        if re.search(r"AI产品|人工智能产品", b, re.I): s += 8
        if re.search(r"芯片|半导体|集成电路|智能硬件|集成电路|电子/", ind): s += 10
        if re.search(r"C端", b): s += 2
    elif d == "互联网产品经理":
        s = 50
        if re.search(r"数据产品|数据分析", b): s += 5
        if re.search(r"B端产品", b): s += 6
        if re.search(r"软件产品|ERP|SaaS|网络安全", b): s += 5
        if re.search(r"芯片|半导体|集成电路", ind): s += 10
    elif d == "AI全栈":
        s = 45
        if re.search(r"训练师|实施|应用工程师|落地|交付|陪跑", title): s += 15
        if re.search(r"0-20人", scale): s += 10
        elif re.search(r"20-99人", scale): s += 5
        if re.search(r"Agent|智能体", b, re.I): s += 8
        lo, hi = parse_sal(j.get("salary"))
        if hi >= 45: s -= 10
        hits = [k for k, rx in {"React": r"React", "Vue": r"Vue", "TS": r"TypeScript", "Node": r"Node", "Python": r"Python",
                                "Go": r"Golang", "Redis": r"Redis", "MySQL": r"MySQL", "MongoDB": r"MongoDB"}.items() if re.search(rx, b, re.I)]
        if hits: s += min(6, len(hits))
    else:
        qc_hit = re.search(r"\bSTA\b|时序|LEC|形式验证|Muse|Lint|CDC|签核|signoff|质量|QC", b, re.I)
        s = 30
        if qc_hit: s += 28
        else:
            if d == "芯片验证" and re.search(r"UVM|SystemVerilog|验证平台|testbench", b, re.I): s -= 8
            if d == "数字后端":
                if re.search(r"PR|物理设计|布局布线|place|route", b, re.I): s -= 8
                elif re.search(r"后端工程师经验|后端EDA", b): s += 4
            if d == "芯片测试":
                if re.search(r"ATE|CP|FT|测试程序|probe", b, re.I): s -= 5
                elif re.search(r"测试|量产", b): s += 3
        if re.search(r"AI|智能|大模型|机器学习", b, re.I): s += 12
    if j["_city"] == "合肥": s += 3
    return s

def tier(s):
    return next(name for t, name in TIERS if s >= t)

@dataclass
class Funnel:
    raw: int; matched: int; after_degree: int; final: int
    tiers: dict; total_score: int; final_ids: set

def load_legacy_jobs(conn: sqlite3.Connection) -> list[dict]:
    """按来源文件名（run_tasks.query_json.source_name）排序、文件内 item_index 顺序读取 raw_json；
    _city/_kw 取自文件名。SQLite 对 UTF-8 文本按字节排序，与 Python 按码点排序一致。"""
    rows = conn.execute("""select json_extract(t.query_json, '$.source_name') as source_name, s.item_index, s.raw_json
                           from sightings s join run_tasks t on t.task_id = s.task_id
                           where s.raw_kind = 'legacy_mapped' and s.raw_json is not null
                           order by source_name, s.item_index""").fetchall()
    out = []
    for source_name, _, raw in rows:
        j = json.loads(raw); city, kw = source_name[:-5].split("_", 1)
        j["_city"], j["_kw"] = city, kw
        out.append(j)
    return out

def run_funnel(jobs: list[dict], exp_keep: tuple[str, ...]) -> Funnel:
    seen, uniq = set(), []
    for j in jobs:
        jid = j.get("job_id")
        if not jid or jid in seen: continue
        seen.add(jid)
        exp, deg = parse_tags(j.get("tags") or "")
        j = dict(j, _exp=exp, _deg=deg, _dir=classify(j)); uniq.append(j)
    matched = [j for j in uniq if j["_dir"]]
    n_deg = [j for j in matched if j["_deg"] not in ("硕士", "博士", "研究生")]
    final = [j for j in n_deg if j["_exp"] in exp_keep]
    scores = [score_job(j) for j in final]
    tiers = {}
    for s in scores: tiers[tier(s)] = tiers.get(tier(s), 0) + 1
    return Funnel(len(uniq), len(matched), len(n_deg), len(final), tiers, sum(scores), {j["job_id"] for j in final})
