# tests/unit/test_skill_docs_match_schemas.py
"""每个 schema 的 required 字段名（含嵌套对象）必须出现在对应参考文档里；
文档中每个 JSON 示例块都带 schema 标记，且逐块通过对应 schema。"""
import json, pathlib, re
import pytest
from where_my_job.validate.schema import schema_issues

REPO = pathlib.Path(__file__).resolve().parents[2]
REFS = REPO / "skill" / "references"
SCHEMAS = REPO / "src" / "where_my_job" / "config" / "schemas"

DOC_FOR = {
    "profile": "profile-schema.md",
    "strategy": "strategy-schema.md",
    "scoring": "scoring-schema.md",
    "panel": "panel-schema.md",
    "evidence": "evidence-report-schema.md",
    "report": "evidence-report-schema.md",
    "event": "event-schema.md",
    "stream": "stream-schema.md",
}

def _required_names(schema: dict) -> set[str]:
    names = set()
    def walk(node):
        if isinstance(node, dict):
            for r in node.get("required", []):
                if isinstance(r, str):
                    names.add(r)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(schema)
    return names

@pytest.mark.parametrize("kind", sorted(DOC_FOR))
def test_required_fields_are_documented(kind):
    schema = json.loads((SCHEMAS / f"{kind}.schema.json").read_text(encoding="utf-8"))
    doc = (REFS / DOC_FOR[kind]).read_text(encoding="utf-8")
    missing = sorted(n for n in _required_names(schema) if f"`{n}`" not in doc and f'"{n}"' not in doc)
    assert not missing, f"{DOC_FOR[kind]} 未提到 {kind} schema 的必填字段: {missing}"

@pytest.mark.parametrize("doc_name", sorted(set(DOC_FOR.values())))
def test_every_doc_example_passes_its_schema(doc_name):
    text = (REFS / doc_name).read_text(encoding="utf-8")
    blocks = re.findall(
        r"<!-- schema: ([a-z_]+) -->\s*```json\n(.*?)\n```", text, re.S)
    assert blocks, doc_name
    assert len(blocks) == len(re.findall(r"^```json$", text, re.M)), doc_name
    for kind, block in blocks:
        assert DOC_FOR[kind] == doc_name
        obj = json.loads(block)
        issues = schema_issues(kind, obj)
        assert issues == [], (doc_name, kind, [(i.path, i.message) for i in issues])
