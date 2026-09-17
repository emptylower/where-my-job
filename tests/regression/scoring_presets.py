# tests/regression/scoring_presets.py
"""从带 sha256 的私有 manifest 生成 legacy-20260914 / handoff-intent 冻结 scoring。只写测试临时目录。"""
from pathlib import Path

def frozen_scoring(manifest, include_campus):
    def match(field, pattern, ignore=False):
        out = {"field": field, "match": pattern}
        if ignore:
            out["flags"] = "i"
        return out
    def both(*nodes):
        return {"all": list(nodes)}
    def either(*nodes):
        return {"any": list(nodes)}
    def neg(node):
        return {"not": node}
    blob, whole = "title_skills", "title_skills_industry"
    chip = either(match("company_industry", r"电子/半导体|半导体|集成电路|芯片"),
                  match(blob, r"芯片|IC\b|半导体|数字后端|模拟|晶圆|流片|FPGA|集成电路", True))
    verify = match(blob, r"验证|UVM|SystemVerilog|SV\b|DV\b|Emulation|仿真", True)
    backend = both(match(blob, r"后端|物理设计|布局布线|\bPR\b|版图|STA|时序|P&R|APR", True),
                   neg(match(blob, r"软件|Java|Python|Golang|PHP|Web|服务端")))
    testing = both(match(blob, r"测试|\bATE\b|量产|芯片测试|CP\b|FT\b", True),
                   match(blob, r"芯片|IC|半导体|晶圆|Wafer|ATE|SoC", True))
    ai_stack = both(match(blob, r"全栈|全端|Full[- ]?Stack|前端.*后端", True),
                    match(blob, r"AI|人工智能|大模型|LLM|AIGC|机器学习|智能|GPT", True))
    pm = match(blob, r"产品经理|产品总监|产品负责人|PM\b")
    ai_pm = both(pm, match(blob, r"AI|人工智能|大模型|LLM|AIGC|智能", True))
    net_pm = both(pm, match("company_industry", r"互联网|软件|人工智能|游戏|电子商务|数据服务|企业服务|智能硬件|物联网|信息安全|社交|在线教育|消费电子|通信"))
    classify = [{"dir": direction, "when": node} for direction, node in [
        ("芯片验证", both(chip, verify)), ("数字后端", both(chip, backend)),
        ("芯片测试", both(chip, testing)), (None, chip), ("AI全栈", ai_stack),
        ("AI产品经理", ai_pm), ("互联网产品经理", net_pm)]]
    allow = ["经验不限", "应届生", "在校生", "1年以内", "1-3年", "3年以内", "3年及以下"]
    if include_campus:
        allow.append("在校/应届")
    score = {}
    def direction(name, base):
        score[name] = {"base": base, "base_reason": "冻结历史偏好基分；不表示录取率", "rules": []}
    def rule(name, rid, delta, node, reason):
        score[name]["rules"].append({"id": rid, "when": node, "add": delta, "reason": reason})
    direction("AI产品经理", 60)
    for rid, delta, field, pattern, ignore, reason in [
        ("aipm-tech",12,whole,r"语义类AI|机器学习类AI|视觉类AI|语音类AI|Agent|AI机器人",True,"AI技术标签；职责和本人能力待核验"),
        ("aipm-b",8,whole,r"B端产品|中后台",False,"B端/中后台偏好"),
        ("aipm-tool",6,whole,r"低代码|工具|效率",False,"工具/效率方向偏好"),
        ("aipm-ai",8,whole,r"AI产品|人工智能产品",True,"AI产品标签匹配，实际经验待核验"),
        ("aipm-chip",10,"company_industry",r"芯片|半导体|集成电路|智能硬件|集成电路|电子/",False,"行业背景偏好"),
        ("aipm-c",2,whole,r"C端",False,"C端标签偏好")]:
        rule("AI产品经理", rid, delta, match(field, pattern, ignore), reason)
    direction("互联网产品经理", 50)
    for rid, delta, field, pattern in [
        ("pm-data",5,whole,r"数据产品|数据分析"), ("pm-b",6,whole,r"B端产品"),
        ("pm-saas",5,whole,r"软件产品|ERP|SaaS|网络安全"),
        ("pm-chip",10,"company_industry",r"芯片|半导体|集成电路")]:
        rule("互联网产品经理", rid, delta, match(field, pattern), "冻结历史标签偏好，实际要求待JD核验")
    direction("AI全栈", 45)
    rule("AI全栈", "stack-delivery", 15, match("title", r"训练师|实施|应用工程师|落地|交付|陪跑"), "偏好实施交付方向；编码要求待核验")
    small = match("company_scale", r"0-20人")
    rule("AI全栈", "stack-small", 10, small, "历史小团队偏好，不推断面试形式")
    rule("AI全栈", "stack-mid", 5, both(neg(small), match("company_scale", r"20-99人")), "历史团队规模偏好")
    rule("AI全栈", "stack-agent", 8, match(whole, r"Agent|智能体", True), "Agent标签偏好")
    rule("AI全栈", "stack-pay", -10, {"field": "salary_hi", "gte": 45}, "历史高薪准备成本偏好；编码要求待核验")
    score["AI全栈"]["rules"].append({"id": "stack-skills", "reason": "去重技术类别命中，最多6分",
        "skills_hit": {"field": whole, "per_category": 1, "cap": 6, "flags": "i", "categories": {
            "React": "React", "Vue": "Vue", "TS": "TypeScript", "Node": "Node", "Python": "Python",
            "Go": "Golang", "Redis": "Redis", "MySQL": "MySQL", "MongoDB": "MongoDB"}}})
    qc = match(whole, r"\bSTA\b|时序|LEC|形式验证|Muse|Lint|CDC|签核|signoff|质量|QC", True)
    for name, prefix in [("芯片验证", "dv"), ("数字后端", "pr"), ("芯片测试", "test")]:
        direction(name, 30)
        rule(name, prefix + "-qc", 28, qc, "QC/签核关键词匹配，具体工作内容待核验")
        if name == "芯片验证":
            rule(name, prefix + "-coding", -8, both(neg(qc), match(whole, r"UVM|SystemVerilog|验证平台|testbench", True)), "验证编码要求的历史准备成本")
        elif name == "数字后端":
            physical = match(whole, r"PR|物理设计|布局布线|place|route", True)
            rule(name, prefix + "-physical", -8, both(neg(qc), physical), "后端实现要求的历史准备成本")
            rule(name, prefix + "-flow", 4, both(neg(qc), neg(physical), match(whole, r"后端工程师经验|后端EDA")), "后端流程标签偏好")
        else:
            programming = match(whole, r"ATE|CP|FT|测试程序|probe", True)
            rule(name, prefix + "-programming", -5, both(neg(qc), programming), "测试程序要求的历史准备成本")
            rule(name, prefix + "-flow", 3, both(neg(qc), neg(programming), match(whole, r"测试|量产")), "测试/量产流程标签偏好")
        rule(name, prefix + "-ai", 12, match(whole, r"AI|智能|大模型|机器学习", True), "芯片与AI交叉标签偏好")
    files = sorted([{"name": Path(item["path"]).name, "sha256": item["sha256"]}
                    for item in manifest["files"]], key=lambda item: item["name"])
    return {"schema_version": 2, "profile_revision": "legacy-20260914", "campus_policy": "include",
            "input_selection": "legacy-20260914", "legacy_input": {"files": files},
            "classify": classify, "exclude": [
                {"id": "legacy-degree", "when": {"field": "degree", "in": ["硕士", "博士", "研究生"]}, "reason": "冻结历史学历过滤"},
                {"id": "legacy-experience", "when": neg({"field": "exp", "in": allow}), "reason": "冻结历史经验白名单；非当前资格认证"}],
            "score": score, "global": [{"id": "preferred-city", "when": {"field": "city", "eq": "合肥"}, "add": 3, "reason": "冻结历史来源城市偏好"}],
            "tiers": {"S": 90, "A": 75, "B": 60, "C": 40}, "fallback_tier": "D"}
