# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## panel

只读公开列，不接受 SQL/HTML/JS。sort.by、filters.column、符号算子、charts.by 与 timeline.enabled/streams 是正式键名。表格由 columns 控制，bar 为图表。文本比较支持 =、!=、~；数值按类型比较。渲染使用固定 as_of 及同一读事务，显示截断、采样条件、校园政策来源和版本状态。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.title` (`title`) | 否 | {"type": "string", "maxLength": 120} |
| `$.columns` (`columns`) | 是 | {"type": "array", "maxItems": 30} |
| `$.sort` (`sort`) | 否 | {"type": "object"} |
| `$.sort.by` (`by`) | 是 | {"type": "string"} |
| `$.sort.desc` (`desc`) | 否 | {"type": "boolean"} |
| `$.filters` (`filters`) | 否 | {"type": "array", "maxItems": 20} |
| `$.filters[].column` (`column`) | 是 | {"type": "string"} |
| `$.filters[].op` (`op`) | 是 | {"type": "string", "enum": ["=", "!=", ">=", "<=", ">", "<", "~"]} |
| `$.filters[].value` (`value`) | 是 | {"type": ["string", "number"]} |
| `$.charts` (`charts`) | 否 | {"type": "array", "maxItems": 4} |
| `$.charts[].type` (`type`) | 是 | {"type": "string", "enum": ["bar"]} |
| `$.charts[].by` (`by`) | 是 | {"type": "string", "enum": ["dir", "tier", "city", "exp", "degree", "report_state", "application_state"]} |
| `$.page_size` (`page_size`) | 否 | {"type": "integer", "minimum": 1, "maximum": 500} |
| `$.show_unknown_in_main` (`show_unknown_in_main`) | 否 | {"type": "boolean"} |
| `$.timeline` (`timeline`) | 否 | {"type": "object"} |
| `$.timeline.enabled` (`enabled`) | 否 | {"type": "boolean"} |
| `$.timeline.streams` (`streams`) | 否 | {"type": "array", "maxItems": 10} |

含条件分支的必填名称：`by`、`column`、`columns`、`op`、`schema_version`、`type`、`value`。

<!-- schema: panel -->
```json
{
  "schema_version": 1,
  "title": "合成数据演示 — where-my-job",
  "columns": [
    "tier",
    "score",
    "dir",
    "title",
    "company_name",
    "city",
    "salary_text",
    "exp",
    "degree",
    "report_state",
    "application_state",
    "job_url"
  ],
  "sort": {
    "by": "score",
    "desc": true
  },
  "filters": [
    {
      "column": "excluded",
      "op": "=",
      "value": 0
    },
    {
      "column": "match_state",
      "op": "=",
      "value": "current"
    }
  ],
  "charts": [
    {
      "type": "bar",
      "by": "dir"
    },
    {
      "type": "bar",
      "by": "tier"
    }
  ],
  "timeline": {
    "enabled": true,
    "streams": [
      "applications"
    ]
  },
  "page_size": 200
}
```

