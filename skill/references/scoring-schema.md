# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## scoring

规则为有界 AST；all/any/not 使用三值逻辑，not unknown 仍 unknown，仅 true 触发规则。classify 为 first-match，dir=null 可停止分类。技能使用 skills_hit.categories（类别到正则）、per_category/cap；分组使用 score.<方向>.groups。campus_policy 默认 auto：两处经验来源取并集，含经验不限/校园档或无条件时 include，只有年限档时 exclude；显式值覆盖。`experience_allowlist` 本身就会限制资格：不在名单内的岗位由内置规则 `experience-allowlist` 排除，不需要再手写一条同义的 exclude 规则（2026-09-16 实测确认）。手写 exclude 用于白名单覆盖不到的条件（学历、行业、外包等），写了就要与白名单口径一致，不要一边放行一边排除。分数不是概率，理由只能陈述偏好和待核验事项。input_selection 与 legacy_input 只用于维护者的冻结历史回归；agent 生成配置时不写这两个键，保持默认的最新事实输入。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 2} |
| `$.profile_revision` (`profile_revision`) | 是 | {"type": "string", "minLength": 1} |
| `$.campus_policy` (`campus_policy`) | 否 | {"type": "string", "enum": ["auto", "include", "exclude"]} |
| `$.experience_allowlist` (`experience_allowlist`) | 否 | {"type": "array"} |
| `$.input_selection` (`input_selection`) | 否 | {"type": "string", "enum": ["latest", "legacy-20260914"]} |
| `$.legacy_input` (`legacy_input`) | 否 | {"type": "object"} |
| `$.legacy_input.files` (`files`) | 是 | {"type": "array"} |
| `$.legacy_input.files[].name` (`name`) | 是 | {"type": "string", "pattern": "^[^_/\\\\]+_[^/\\\\]+\\.json$"} |
| `$.legacy_input.files[].sha256` (`sha256`) | 是 | {"type": "string", "pattern": "^[0-9a-f]{64}$"} |
| `$.classify` (`classify`) | 是 | {"type": "array"} |
| `$.classify[].dir` (`dir`) | 是 | {"type": ["string", "null"]} |
| `$.classify[].when` (`when`) | 是 | {"$ref": "#/$defs/cond"} |
| `$.exclude` (`exclude`) | 否 | {"type": "array"} |
| `$.exclude[].id` (`id`) | 是 | {"type": "string"} |
| `$.exclude[].when` (`when`) | 是 | {"$ref": "#/$defs/cond"} |
| `$.exclude[].reason` (`reason`) | 是 | {"type": "string", "minLength": 1} |
| `$.score` (`score`) | 是 | {"type": "object"} |
| `$.score.*.base` (`base`) | 是 | {"type": "number"} |
| `$.score.*.base_reason` (`base_reason`) | 是 | {"type": "string", "minLength": 1} |
| `$.score.*.rules` (`rules`) | 否 | {"type": "array"} |
| `$.score.*.groups` (`groups`) | 否 | {"type": "object"} |
| `$.score.*.groups.*.min` (`min`) | 否 | {"type": "number"} |
| `$.score.*.groups.*.max` (`max`) | 否 | {"type": "number"} |
| `$.global` (`global`) | 否 | {"type": "array"} |
| `$.tiers` (`tiers`) | 是 | {"type": "object"} |
| `$.fallback_tier` (`fallback_tier`) | 是 | {"type": "string", "minLength": 1} |
| `#/$defs/rule.id` (`id`) | 是 | {"type": "string"} |
| `#/$defs/rule.reason` (`reason`) | 是 | {"type": "string", "minLength": 1} |
| `#/$defs/rule.when` (`when`) | 否 | {"$ref": "#/$defs/cond"} |
| `#/$defs/rule.add` (`add`) | 否 | {"type": "number"} |
| `#/$defs/rule.group` (`group`) | 否 | {"type": "string", "minLength": 1} |
| `#/$defs/rule.skills_hit` (`skills_hit`) | 否 | {"type": "object"} |
| `#/$defs/rule.skills_hit.field` (`field`) | 否 | {"type": "string"} |
| `#/$defs/rule.skills_hit.categories` (`categories`) | 是 | {"type": "object"} |
| `#/$defs/rule.skills_hit.per_category` (`per_category`) | 否 | {"type": "number", "minimum": 0} |
| `#/$defs/rule.skills_hit.cap` (`cap`) | 否 | {"type": "number", "minimum": 0} |
| `#/$defs/rule.skills_hit.flags` (`flags`) | 否 | {"type": "string", "enum": ["i"]} |

含条件分支的必填名称：`base`、`base_reason`、`categories`、`classify`、`dir`、`fallback_tier`、`files`、`id`、`name`、`profile_revision`、`reason`、`schema_version`、`score`、`sha256`、`tiers`、`when`。

<!-- schema: scoring -->
```json
{
  "schema_version": 2,
  "profile_revision": "synthetic-qc-to-aipm-v1",
  "campus_policy": "auto",
  "experience_allowlist": [
    "经验不限",
    "1-3年"
  ],
  "classify": [
    {
      "dir": "AI产品经理",
      "when": {
        "all": [
          {
            "field": "title",
            "match": "产品经理"
          },
          {
            "field": "title_skills",
            "match": "AI|人工智能|大模型|Agent",
            "flags": "i"
          }
        ]
      }
    }
  ],
  "exclude": [
    {
      "id": "degree-limit",
      "when": {
        "field": "degree",
        "in": [
          "硕士",
          "博士"
        ]
      },
      "reason": "当前画像未提供该学历资格，需按明确要求核实"
    },
    {
      "id": "experience-limit",
      "when": {
        "all": [
          {
            "not": {
              "field": "exp",
              "in": [
                "经验不限",
                "1-3年"
              ]
            }
          },
          {
            "not": {
              "field": "exp",
              "in": [
                "在校生",
                "应届生",
                "在校/应届"
              ]
            }
          }
        ]
      },
      "reason": "不在本次选择的经验范围内；校园标签由校园政策单独处理"
    }
  ],
  "score": {
    "AI产品经理": {
      "base": 60,
      "base_reason": "本次优先探索方向",
      "rules": [
        {
          "id": "agent-interest",
          "when": {
            "field": "title_skills",
            "match": "Agent|智能体",
            "flags": "i"
          },
          "add": 12,
          "reason": "符合用户的主题偏好；具体职责及编码要求待 JD 核实"
        }
      ]
    }
  },
  "global": [
    {
      "id": "preferred-city",
      "when": {
        "field": "city",
        "eq": "合肥"
      },
      "add": 3,
      "reason": "符合本次城市偏好"
    }
  ],
  "tiers": {
    "S": 90,
    "A": 75,
    "B": 60,
    "C": 40
  },
  "fallback_tier": "D"
}
```

