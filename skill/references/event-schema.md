# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## event

首次 applied 的 subject_kind 是 application，不提供 subject_id，payload.job_id 指向岗位，事务内创建身份。随后使用返回的 application_id 作为 subject_id；event list --subject 过滤该 application_id，不能传岗位 ID 代替。stream_revision 必须明确，原请求重试维持原版本。纠错例中 app/evt 为合成协议示例，操作时使用 event add 返回的身份和当前链末端。replace 是完整替代，retract 保留历史；控制事件时间与替代事实时间分开。72 小时仅提醒，不能视为拒绝。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.stream` (`stream`) | 是 | {"type": "string", "minLength": 1, "maxLength": 80} |
| `$.stream_revision` (`stream_revision`) | 是 | {"type": "integer", "minimum": 1} |
| `$.type` (`type`) | 是 | {"type": "string", "minLength": 1, "maxLength": 64} |
| `$.subject_kind` (`subject_kind`) | 是 | {"enum": ["job", "company", "application", "none"]} |
| `$.subject_id` (`subject_id`) | 否 | {"type": ["string", "null"], "maxLength": 200} |
| `$.occurred_at` (`occurred_at`) | 是 | {"type": "string", "minLength": 20, "maxLength": 40} |
| `$.payload` (`payload`) | 是 | {"type": "object"} |
| `$.idempotency_key` (`idempotency_key`) | 是 | {"type": "string", "minLength": 8, "maxLength": 200} |
| `$.origin` (`origin`) | 是 | {"enum": ["agent", "user"]} |
| `$.corrected` (`corrected`) | 否 | {"type": "object"} |
| `$.corrected.corrected_event_id` (`corrected_event_id`) | 是 | {"type": "string", "minLength": 1} |
| `$.corrected.op` (`op`) | 是 | {"enum": ["replace", "retract"]} |
| `$.corrected.original_type` (`original_type`) | 否 | {"type": "string"} |
| `$.corrected.replacement_payload` (`replacement_payload`) | 否 | {"type": "object"} |
| `$.corrected.replacement_occurred_at` (`replacement_occurred_at`) | 否 | {"type": "string"} |

含条件分支的必填名称：`corrected_event_id`、`idempotency_key`、`occurred_at`、`op`、`origin`、`payload`、`schema_version`、`stream`、`stream_revision`、`subject_kind`、`type`。

<!-- schema: event -->
```json
{
  "schema_version": 1,
  "stream": "applications",
  "stream_revision": 1,
  "type": "applied",
  "subject_kind": "application",
  "occurred_at": "2026-09-10T08:00:00Z",
  "payload": {
    "job_id": "boss:SYN0001aaaa"
  },
  "idempotency_key": "applied-synthetic-0001",
  "origin": "user"
}
```

<!-- schema: event -->
```json
{
  "schema_version": 1,
  "stream": "applications",
  "stream_revision": 1,
  "type": "corrected",
  "subject_kind": "application",
  "subject_id": "app_SYN0001",
  "occurred_at": "2026-09-14T08:00:00Z",
  "payload": {},
  "idempotency_key": "corrected-synthetic-0001",
  "origin": "user",
  "corrected": {
    "corrected_event_id": "evt_SYN0001",
    "op": "replace",
    "original_type": "applied",
    "replacement_payload": {
      "job_id": "boss:SYN0001aaaa"
    },
    "replacement_occurred_at": "2026-09-10T09:00:00Z"
  }
}
```

## 内置流 `applications` 的 payload 字段

每种事件类型只接受下面这些字段，类型不符会以 `SEMANTIC_INVALID` 拒绝（`path` 指向具体字段）。时间必须是带时区且真实存在的 ISO 字符串。

| 事件类型 | 必填 | 可选字段与类型 |
|---|---|---|
| `applied` | `job_id` | `job_id` 字符串、`channel` 字符串、`note` 字符串 |
| `replied` | — | `note` 字符串 |
| `interview` | — | `round` **字符串**（不是整数）、`at` 带时区时间、`note` 字符串 |
| `offer` | — | `note` 字符串 |
| `rejected` | — | `note` 字符串 |
| `withdrawn` | — | `note` 字符串 |

`corrected` 是所有流内置的控制事件，`op` 只能是 `replace` 或 `retract`。
