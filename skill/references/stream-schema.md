# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## stream

流名 custom. 开头，只允许固定字段类型。声明不可变；升版只新增类型或可选字段，不改主体、必填集合及已有字段类型。corrected 是保留控制类型。validate 不激活，写候选文件不激活；只有 register 事务内切换活动版本。projection/latest_by 返回尚未支持。时间线保留 scheduled 和 done 两条事实，不跨类型自动填补字段。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.stream` (`stream`) | 是 | {"type": "string", "minLength": 1, "maxLength": 80} |
| `$.stream_revision` (`stream_revision`) | 是 | {"type": "integer", "minimum": 1} |
| `$.subject_kind` (`subject_kind`) | 是 | {"type": "string"} |
| `$.types` (`types`) | 是 | {"type": "object"} |
| `$.types.*.required` (`required`) | 是 | {"type": "array", "maxItems": 64} |
| `$.types.*.fields` (`fields`) | 是 | {"type": "object"} |
| `$.types.*.fields.*.oneOf[1].enum` (`enum`) | 是 | {"type": "array", "maxItems": 64} |
| `$.projection` (`projection`) | 否 | {} |
| `$.latest_by` (`latest_by`) | 否 | {} |

含条件分支的必填名称：`enum`、`fields`、`items`、`maxItems`、`required`、`schema_version`、`stream`、`stream_revision`、`subject_kind`、`type`、`types`。

<!-- schema: stream -->
```json
{
  "schema_version": 1,
  "stream": "custom.interviews",
  "stream_revision": 1,
  "subject_kind": "application",
  "types": {
    "scheduled": {
      "required": [
        "round",
        "at"
      ],
      "fields": {
        "round": "string",
        "at": "datetime",
        "format": {
          "enum": [
            "onsite",
            "video",
            "phone"
          ]
        }
      }
    },
    "done": {
      "required": [
        "round"
      ],
      "fields": {
        "round": "string",
        "questions": "string",
        "self_rating": "integer"
      }
    }
  }
}
```

