# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## strategy

按用户要的范围写，不要替用户缩小（规则见 SKILL.md「采集范围」）。展开动作数必须同时满足配置预算和 80 硬上限；24 小时账本跨 run 共用。405 是 10–20K，不是至少 10K。筛选码表以 config.search_codes 为唯一来源，未知码拒绝，dry-run 显示人可读意义。

**城市不是白名单。** 内置合肥、上海、北京、深圳、广州、杭州、武汉七个便利名；其余城市直接写平台城市码（形如 `101270100`），或在 `city_codes` 里给出名字到码的映射再按名字用。`city_codes` 优先于内置名。本工具不内置全国城市表——没有可信来源，编出来的码就是静默错值；码由用户提供。反查不到名字时，dry-run 的 `city` 显示码本身，不编名字。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.name` (`name`) | 是 | {"type": "string", "minLength": 1, "maxLength": 80} |
| `$.city_codes` (`city_codes`) | 否 | {"type": "object", "maxProperties": 400}，值须匹配 `^101[0-9]{6}$` |
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

多城多页、自带城市码映射、裸码与便利名混用：

<!-- schema: strategy -->
```json
{
  "schema_version": 1,
  "name": "多城多页合成配置",
  "city_codes": {
    "成都": "101270100",
    "南京": "101190100"
  },
  "searches": [
    {
      "keywords": [
        "AI产品经理",
        "产品经理"
      ],
      "cities": [
        "合肥",
        "成都",
        "南京",
        "101280600"
      ],
      "pages": 5,
      "boss_filters": {
        "degree": [
          "本科"
        ],
        "experience": [
          "3-5年",
          "1-3年"
        ]
      }
    }
  ],
  "budget": {
    "max_pages_per_run": 80,
    "pause_between_actions_sec": [
      12,
      22
    ]
  }
}
```
