# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## profile

技能是用户自述，不是认证。targets.experience_scope 记录用户范围；scoring.experience_allowlist 及资格规则来自同一选择。CLI 不默认读取简历全文。画像变更必须更换 profile_revision，旧匹配和报告按版本提示过期。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.profile_revision` (`profile_revision`) | 是 | {"type": "string", "minLength": 1} |
| `$.summary` (`summary`) | 是 | {"type": "string", "minLength": 1, "maxLength": 2000} |
| `$.skills` (`skills`) | 否 | {"type": "array"} |
| `$.skills[].name` (`name`) | 是 | {"type": "string", "minLength": 1} |
| `$.skills[].level` (`level`) | 否 | {"type": "string", "enum": ["familiar", "working", "proficient"]} |
| `$.targets` (`targets`) | 否 | {"type": "object"} |
| `$.targets.directions` (`directions`) | 否 | {"type": "array"} |
| `$.targets.cities` (`cities`) | 否 | {"type": "array"} |
| `$.targets.salary_floor_k` (`salary_floor_k`) | 否 | {"type": "number", "minimum": 0} |
| `$.targets.experience_scope` (`experience_scope`) | 否 | {"type": "array"} |
| `$.redlines` (`redlines`) | 否 | {"type": "array"} |
| `$.notes` (`notes`) | 否 | {"type": "string", "maxLength": 4000} |

含条件分支的必填名称：`name`、`profile_revision`、`schema_version`、`summary`。

<!-- schema: profile -->
```json
{
  "schema_version": 1,
  "profile_revision": "synthetic-qc-to-aipm-v1",
  "summary": "合成画像：有芯片 QC 流程经验，希望尝试 AI 产品方向；技能均为自述，待具体岗位核验。",
  "skills": [
    {
      "name": "需求拆解与验收",
      "level": "working"
    },
    {
      "name": "Agent 工具使用",
      "level": "working"
    }
  ],
  "targets": {
    "directions": [
      "AI产品经理"
    ],
    "cities": [
      "合肥"
    ],
    "experience_scope": [
      "经验不限",
      "1-3年"
    ]
  },
  "redlines": [
    "明确要求硕士及以上"
  ],
  "notes": "合成示例，非真实用户。"
}
```

