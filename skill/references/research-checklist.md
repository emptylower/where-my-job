# 站外调查清单

每一项：先看工具是否可用；不可用就在报告"未知项"写"未核验（工具不可用）"。每条结果用 `where-my-job evidence add JOB_ID --file F` 写入，`kind=web_page` 与 `kind=document` 必须带 https URL；用户口述用 `kind=user_statement`，不冒充网页。

| 项 | 怎么查 | 可以说 | 不可以说 |
|---|---|---|---|
| 公司官网招聘页 | WebFetch 官网"加入我们"页，看是否有同岗位及页面自述日期 | "官网招聘页在抓取时列出同名岗位（ev_…），页面自述日期为 [原值]" | "官网没列就是假岗" |
| 工商信息 | 天眼查、企查查类 MCP（若用户的 agent 有），查成立时间、参保人数、经营状态 | "参保人数 [n]（[来源]，[抓取日期]）" | "参保人数少所以不招人" |
| 近期新闻 | WebSearch 公司名加融资、裁员、新业务，只取有日期与来源的 | "[日期] [媒体] 报道 [事件]（ev_…），可能与本岗位相关（推断）" | "已证明新编制或无离职潮" |
| 其他平台同名岗位 | WebSearch 岗位标题加公司名 | "在 [平台] 也见到同名岗位，页面自述日期 [原值]（ev_…）" | "多平台发布就是急招" |
| BOSS 公司页计数 | 来自 `deepdive` 的公司页证据 | "页面显示 BOSS 数 a、岗位数 b，比值 [x]（快照 [时间]）" | "1:22 一定养鱼、50:394 一定真招" |
| 观察记录 | 来自 `job show` 的 first_seen_at、last_seen_at 与 hit_count | "本工具在 [首次日期] 与 [末次日期] 之间共观察 N 次，覆盖仅限本工具的搜索" | "岗位在首次观察日发布、一直在招、仍有编制" |
| 招聘者头衔 | 详情页证据 | "页面自述头衔 [文本]" | "招聘者必然是业务负责人" |
| 用户投递记录 | `event list --stream applications --subject <application_id>` | "投递后 72 小时无回复，建议跟进" | "已拒绝或假岗位" |

## 写入证据的最小字段

- `schema_version`：常量 1。
- `job_id` 或 `company_id`：必须已存在；同时给出时，公司必须是该岗位已核实的公司。
- `kind`：`web_page`、`user_statement` 或 `document`。
- `url`：`web_page` 与 `document` 必填，https（与子计划 04 `URL_REQUIRED_KINDS = ("web_page", "document")` 一致）；`user_statement` 可省略。
- `captured_at`：带时区的真实时间，例如 `2026-09-14T10:00:00Z`。
- `published_at`：页面自述的发布时间；未知时省略，不猜零点，不只写日期。
- `excerpt`：原文摘录，不写结论。
- `structured`：可选，只放页面原值。
- `source_note`：一句话说明你是怎么找到的。
- `idempotency_key`：至少 8 个字符，建议 `sha256(url + excerpt)` 前 32 位。
- `origin`：可以不写，由命令的 `--origin` 决定（默认 agent）；如果写在文件里，必须与 `--origin` 一致，且不能写 `cli`。

## 不做

不登录任何第三方站点，不提交表单，不在任何站点留下用户身份；不为凑齐维度编造条目；不把搜索引擎摘要当原文引用。
