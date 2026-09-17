# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## strategy

首次为 1 关键词×1 城×1 页。展开动作数必须同时满足配置预算和 80 硬上限；24 小时账本跨 run 共用。405 是 10–20K，不是至少 10K。码表以 config.search_codes 为唯一来源，未知码拒绝，dry-run 显示人可读意义。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.name` (`name`) | 是 | {"type": "string", "minLength": 1, "maxLength": 80} |
| `$.searches` (`searches`) | 是 | {"type": "array"} |
| `$.searches[].keywords` (`keywords`) | 是 | {"type": "array"} |
| `$.searches[].cities` (`cities`) | 是 | {"type": "array"} |
| `$.searches[].pages` (`pages`) | 否 | {"type": "integer", "minimum": 1, "maximum": 80} |
| `$.searches[].boss_filters` (`boss_filters`) | 否 | {"type": "object"} |
| `$.searches[].boss_filters.experience` (`experience`) | 否 | {"$ref": "#/$defs/filterValue"} |
| `$.searches[].boss_filters.degree` (`degree`) | 否 | {"$ref": "#/$defs/filterValue"} |
| `$.searches[].boss_filters.salary` (`salary`) | 否 | {"$ref": "#/$defs/filterValue"} |
| `$.searches[].boss_filters.scale` (`scale`) | 否 | {"$ref": "#/$defs/filterValue"} |
| `$.searches[].boss_filters.stage` (`stage`) | 否 | {"$ref": "#/$defs/filterValue"} |
| `$.searches[].boss_filters.industry` (`industry`) | 否 | {"$ref": "#/$defs/filterValue"} |
| `$.budget` (`budget`) | 是 | {"type": "object"} |
| `$.budget.max_pages_per_run` (`max_pages_per_run`) | 否 | {"type": "integer", "minimum": 1, "maximum": 80} |
| `$.budget.pause_between_actions_sec` (`pause_between_actions_sec`) | 是 | {"type": "array", "maxItems": 2} |

含条件分支的必填名称：`budget`、`cities`、`keywords`、`name`、`pause_between_actions_sec`、`schema_version`、`searches`。

<!-- schema: strategy -->
```json
{
  "schema_version": 1,
  "name": "首次单页合成配置",
  "searches": [
    {
      "keywords": [
        "AI产品经理"
      ],
      "cities": [
        "合肥"
      ],
      "pages": 1,
      "boss_filters": {}
    }
  ],
  "budget": {
    "max_pages_per_run": 1,
    "pause_between_actions_sec": [
      12,
      22
    ]
  }
}
```

