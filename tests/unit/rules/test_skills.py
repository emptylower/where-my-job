# tests/unit/rules/test_skills.py
from where_my_job.rules.skills import count_hits, normalize_skill

def test_normalize():
    assert normalize_skill("  React.js ") == "react.js" and normalize_skill("Node.js开发经验") == "node.js开发经验"

def test_count_hits_dedup_and_cap():
    cats = {"React": "React", "Vue": "Vue", "TS": "TypeScript", "Node": "Node", "Py": "Python", "Go": "Golang", "Redis": "Redis"}
    text = "React react Vue TypeScript Node Python Golang Redis MySQL"
    hits, n = count_hits(text, cats, flags_i=True)
    assert hits == ["React", "Vue", "TS", "Node", "Py", "Go", "Redis"] and n == 7
    assert count_hits("nothing", cats, flags_i=True) == ([], 0)
    assert count_hits(None, cats, flags_i=True) == ([], 0)
