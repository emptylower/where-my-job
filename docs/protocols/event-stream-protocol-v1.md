<!-- docs/protocols/event-stream-protocol-v1.md -->
# 事件流协议 v1（冻结于子计划 03 完成时）

- 声明文件 schema：`src/where_my_job/config/schemas/stream.schema.json`；事件文件 schema：`event.schema.json`。两者 `schema_version=1`，改动需升版并保留旧版读取。
- 事件请求必须显式给出 `stream_revision`。新业务事件只能绑定活动版本；纠错绑定根事件的版本；已成功请求的重试按请求自己绑定的版本比较，不要求该版本仍活动。
- 幂等键至少 8 个字符。比较键：sha256(canonical_json({stream, stream_revision(请求绑定), type, subject, occurred_at(UTC), payload, origin, corrected{target, op, original_type, replacement_payload, replacement_occurred_at(UTC)}}))。`subject` 为 `[subject_kind, subject_id, payload.job_id(仅 applied)]`；已存 applied 比较时 subject_id 还原为 None。
- 写入顺序：`event add` 只读一次文件 → `write_tx` 内 `service.events.validate_new_request`（schema → 时间解析 → corrected 块结构 → 幂等键查找 → 版本绑定 → 仅新请求做语义校验）→ `store.events.append`（主体、身份、纠错链、有效集合复核）→ 提交。`validate event` 在 `read_tx` 内调用同一 helper，不写入。
- 时间字段（`occurred_at`、`corrected.replacement_occurred_at`、声明为 `datetime` 的 payload 字段）解析失败返回 `SCHEMA_INVALID` 与精确路径；比较一律用解析后的 UTC。
- 内置流 `applications` 定义与哈希：`streams/builtin.py:APPLICATIONS_DEFINITION`，注册于迁移 0003，revision 1。
- 控制类型 `corrected` 的存储形态：`type='corrected'`，`corrected_event_id` 指向当时的链末端，`payload_json` 为 `{"op":"retract"}` 或 `{"op":"replace","original_type":..,"replacement_payload":{..},"replacement_occurred_at":..}`；`occurred_at` 是纠错请求自己的发生时间，`recorded_at` 为写入时间；被替代事实的时间只在 `replacement_occurred_at`。
- 纠错写入后同一事务复核：单后继；applications 流后续事件不早于有效 applied；`_check_effective_application`（唯一有效 applied、有效后续事件必须有有效 applied、内置后续事件不早于投递）。任一失败整体回滚。
- 有效事实：`v_effective_events`（递归 CTE，读侧无深度截断；`chain_depth` 仅诊断）。
- 读取：`timeline_page`（有效事实，按 occurred_at、current_recorded_at、root_id）、`stream_history_page`（原始行，按 recorded_at、event_id）、`history_page`（单条根事件的完整链，按链深度）；均返回 `items/total/limit/offset/truncated`，时间线上限 1000，历史上限 2000。
- 投递状态派生：`v_job_application`（最近有效 applied；最后有效事件类型；72h followup，固定 as_of）。
- `v_jobs` 的 application 列由 Task 3 生成器 stage 3 从 0002 定义生成；0004 用 stage 4 在其上填 report 列。
- 错误码：NOT_FOUND / SCHEMA_INVALID / SEMANTIC_INVALID / UNSUPPORTED_SETTING / RESERVED_KEY / INCOMPATIBLE_REVISION / SUBJECT_MISSING / IDEMPOTENCY_CONFLICT / CORRECTION_NOT_TAIL / CORRECTION_CROSS_STREAM / CORRECTION_FORK / DEPENDENT_EVENTS。
