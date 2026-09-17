# tests/helpers/profile_seed.py
from __future__ import annotations
import json
from where_my_job.paths import atomic_write_text

def write_profile(lay, revision: str = "example-minimal-v1") -> None:
    obj = {"schema_version": 1, "profile_revision": revision,
           "summary": "合成画像：用于报告协议测试，非真实用户。",
           "skills": [{"name": "需求拆解与验收", "level": "working"}],
           "targets": {"directions": ["AI产品经理"], "cities": ["合肥"], "experience_scope": ["经验不限", "1-3年"]},
           "redlines": [], "notes": "合成示例"}
    atomic_write_text(lay.config("profile.json"), json.dumps(obj, ensure_ascii=False), lay=lay)
