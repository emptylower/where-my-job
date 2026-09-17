# where-my-job 设计文档（v1，已被 v3 取代）

> 本文件为 2026-09-14 首版设计，已被 `2026-09-14-where-my-job-design-v3.md` 取代，仅作历史记录。主要被推翻的决定：真实数据作公共示例、直接复用上游高层爬取循环、任意 x_ 扩展表、无校准的真招概率、自动留存清理。


> 日期：2026-09-14 ｜ 状态：设计已过口头评审，待用户通读确认
> 前置材料：`~/Desktop/boss-hunter-handoff/交接文档.md`（今天手工验证链路的完整记录）

---

## 1. 一句话定位

一个本地运行的求职情报工具：用用户自己的 BOSS直聘登录态批量浅爬岗位，按用户画像打分排序，对点名的岗位做"真招还是养鱼"判定与 JD 翻译，输出可视化面板。形态是**确定性 CLI + 一份 SKILL.md**，用户已有的 coding agent（Claude Code / Codex / Hermes 等）通过 SKILL.md 驱动 CLI。

## 2. 商业判断（已定，不再讨论）

| 问题 | 结论 | 依据 |
|---|---|---|
| 做付费 SaaS？ | 不做 | 数据经服务器即触碰不正当竞争判例（微博诉脉脉、前程无忧诉逸橙）；AI 简历工具红海；依赖 BOSS 接口脆弱 |
| 做开源 Skill？ | 做 | 需求信号真实（求职群主动问"什么 Skills 做的"）；本地运行不碰法律线；差异点在"岗位侧情报"，竞品全在简历侧 |
| 回报是什么 | 作品而非收入 | 用户主投 AI 产品经理，一个有真实用户的开源产品是最硬的作品 |
| 永远不做 | 自动投递、多用户数据汇聚 | 前者是 BOSS 封号线，后者是法律线 |

## 3. 形态：CLI + Skill 混合体

```
┌──────────────────────────────┐
│  用户的 coding agent          │  读 SKILL.md，负责 5 处推理
│  (Claude Code / Codex / …)   │
└──────────────┬───────────────┘
               │ 单向调用（agent 调 CLI，CLI 永不调 agent）
               ▼
┌──────────────────────────────┐
│  where-my-job CLI            │  确定性：I/O、风控、存储、规则打分、渲染
│  init/scan/match/panel/…     │
└──────────────┬───────────────┘
               │
   ┌───────────┼───────────────┐
   ▼           ▼               ▼
专用 Chrome   ~/.where-my-job/   默认浏览器
(CDP 9222)   SQLite + JSON      打开 HTML 面板
```

**核心约束**：CLI 不知道 LLM 存在。这一条保证可复跑、可离线测试、LLM 永不进爬取循环。

三种形态的取舍：

| 形态 | 问题 |
|---|---|
| 纯 Skill（agent 亲自跑每步） | agent 进入爬取循环：慢、烧 token、不可复跑、易触发风控 |
| 纯 Agent（自带 LLM 调用） | 用户要配 API key；重造群友已有的 agent 运行时；丢掉分发渠道 |
| **混合体（选定）** | CLI 做确定性部分，agent 只在循环两端推理 |

## 4. 数据模型：三层

原则：**因数据源而定的形状固定，因人而定的形状不可预知。CLI 拥有身份和时间，用户和 agent 拥有含义。**

### 4.1 第一层：核心表（CLI 拥有，固定，版本化迁移）

| 表 | 主键 | 内容 | 谁写 |
|---|---|---|---|
| `jobs` | job_id | 岗位身份 + 解析后的常用字段（title/salary_lo/hi/exp/degree/city/company_link…）+ 最近一次 `raw_json` | scan |
| `sightings` | (job_id, run_id) | 每次扫描目击一行：时间、**API 返回的整条原始 JSON 原样保存**、当次 bossOnline 等易变字段 | scan |
| `runs` | run_id | 扫描批次：strategy 快照、起止时间、请求数、风控状态（ok/blocked） | scan |
| `companies` | company_link | 公司页文本：在招数、BOSS 数、热招列表、工商信息原文、抓取时间 | deepdive |
| `job_details` | job_id | JD 原文、详情页要求（与列表对比）、ld+json upDate、招聘者活跃状态 | deepdive |
| `evidence` | (job_id, source, ts) | 证据条目：CLI 抓的站内证据、agent 查的站外证据（source = cli/agent） | deepdive / agent |
| `deepdives` | job_id | agent 写的判定报告 Markdown、时间 | report set |

**为什么 sightings 存整条原始 JSON**：上游 `map_api_job` 只挑二十余字段，丢弃了 `proxyJob/proxyType/goldHunter/bossCert/jobValidStatus` 等真招信号（字段名需在首次 scan 时对真实响应核对）。原样保存后：以后要任何字段不用重爬；`match` 规则可对全量岗位直接用"代招减分"。

**时间序列价值**：同一岗位多次目击 = 岗位年龄、更新频率、状态变化，是判断养鱼岗最硬的信号，单次快照拿不到。

### 4.2 第二层：标注层（无固定 schema，三方共写）

```sql
CREATE TABLE job_attrs (
  job_id TEXT NOT NULL,
  key    TEXT NOT NULL,
  value  TEXT NOT NULL,   -- JSON
  source TEXT NOT NULL,   -- 'rule' | 'agent' | 'user'
  run_id TEXT,
  ts     TEXT NOT NULL,
  PRIMARY KEY (job_id, key, source)
);
-- company_attrs 同构
```

比喻：贴在复印件上的便利贴，三种颜色。

| source | 谁写 | 何时 | 幂等性 |
|---|---|---|---|
| `rule` | `match` 按 scoring.json 计算 | 每次 match | 全部删除重算 |
| `agent` | agent 推理后 `attr set` | deepdive 后 | 覆盖同 key |
| `user` | 用户手标 | 随时 | 覆盖同 key |

- 同一 key 可三种来源并存；面板显示优先级 user > agent > rule（"规则打分 + agent 精修"无需额外机制）。
- 约定（非结构）：deepdive 后 agent 必须写 `authentic` 与 `jd_translation` 两个 key。
- CLI 提供视图 `v_jobs`：把所有 key 展平成列，agent 与 panel 直接 `SELECT * FROM v_jobs WHERE score >= 75`。

今天数据的映射：`_dir/_score/_rs/tier/excluded` → rule；华然/usmile 判定 → agent；"主攻" → user。

### 4.3 第三层：扩展表（agent 定义，CLI 托管）

比喻：便利贴写不下时另开的笔记本（投递日志、面试复盘、内推人脉）。

- agent 写表定义 JSON 到 `~/.where-my-job/schemas/<name>.json`（列名、类型、枚举、外键 ref）。
- `db migrate` 校验后建成 `x_<name>` 表，记录 `schema_versions`；文件加列 → ALTER TABLE，永不删数据。
- agent 永不直接执行 DDL；写数据用 `db insert`，读用 `db query`（只读）。
- 示例：`x_applications(job_id, applied_at, first_reply_at, stage, note)` 支撑"48 小时回复测速"。

### 4.4 配置文件（`~/.where-my-job/`）

| 文件 | 谁生成 | 内容 |
|---|---|---|
| `profile.json` | agent 访谈 | 学历、经历、能否手写代码、城市、红线、技能树（含自评置信度）、"简历上不会写的真话" |
| `strategies/*.json` | agent | 搜索矩阵 + boss_filters + 本地 exclude + budget，可多份 |
| `scoring.json` | agent 从 profile 推出 | classify 规则 + 分方向打分规则 + global + tiers |
| `panel.json` | agent / 默认 | tabs：每个 tab = SQL + 列配置 + 筛选 + 图表提示 |
| `schemas/*.json` | agent | 第三层表定义 |
| `resume/` | 用户 | 简历原文件，CLI 只记路径永不读内容外发 |

## 5. strategy.json

```json
{
  "name": "主投+兜底",
  "searches": [
    {"keywords": ["AI产品经理","产品经理"], "dir": "产品", "cities": ["合肥","杭州","武汉","上海","广州","深圳","北京"], "pages": 2,
     "boss_filters": {"salary": "405"}},
    {"keywords": ["芯片验证","数字后端","芯片测试"], "dir": "芯片", "cities": ["合肥","上海","深圳"], "pages": 2}
  ],
  "exclude": [
    {"field": "degree", "in": ["硕士","博士"], "reason": "学历红线"},
    {"field": "exp", "in": ["3-5年","5-10年","10年以上"], "reason": "经验≤3年"}
  ],
  "budget": {"max_pages_per_run": 60, "pause_between_pages_sec": [12, 20]}
}
```

- `boss_filters` 复用上游筛选码（scale/stage/salary/experience/degree/industry）。
- 默认建议：城市、薪资下限走服务端筛；经验、学历走本地 exclude（usmile 案例：列表"1-3年"、详情"经验不限"，服务端筛会漏）。agent 生成时自行决定。
- 被 exclude 的岗位仍入库，贴 `excluded` rule 便利贴，可反悔。
- `budget` 是风控参数所在位置；CLI 有安全上限，agent 改不过。默认值 = 今天 35 分钟无异常的参数。

## 6. scoring.json

把 `score_report.py` 的 if 链翻译成数据。算子只有五种：`match`（正则）、`eq`、`gte`、`lte`、`in`；字段用 `|` 合并。

```json
{
  "version": 1,
  "classify": [
    {"dir": "AI产品经理", "all": [{"field": "title", "match": "产品经理"}, {"field": "title|skills", "match": "AI|人工智能|大模型|Agent"}]}
  ],
  "score": {
    "AI产品经理": {"base": 60, "rules": [
      {"if": {"field": "title|skills", "match": "Agent|语义类AI"}, "add": 12, "reason": "AI技术理解(你有agent实战)"},
      {"if": {"field": "company_industry", "match": "芯片|半导体|智能硬件"}, "add": 10, "reason": "懂芯片行业"}
    ]},
    "AI全栈": {"base": 45, "rules": [
      {"if": {"field": "salary_hi", "gte": 45}, "add": -10, "reason": "⚠高薪岗大概率考硬编码"}
    ]}
  },
  "global": [
    {"if": {"field": "city", "eq": "合肥"}, "add": 3, "reason": "合肥本地"},
    {"if": {"field": "raw.proxyJob", "eq": true}, "add": -20, "reason": "代招/猎头挂岗"}
  ],
  "tiers": {"S": 90, "A": 75, "B": 60, "C": 40, "D": 0}
}
```

`match` 输出的 rule 便利贴：`dir`、`score`、`tier`、`reasons`（每分挂理由，可解释）、`excluded`。

## 7. 证据：两级

| 级别 | 来源 | 成本 | 覆盖 |
|---|---|---|---|
| 浅证据 | 列表 API 整条原始 JSON + 自己库里的目击历史 | 零（scan 时已有） | 全部岗位 |
| 深证据 | 详情页（JD、详情要求、upDate、活跃状态）+ 公司页（在招数、BOSS 数、工商原文、热招列表） | 约 1 分钟/岗 | 用户点名的岗位 |
| 站外证据 | agent 用自身工具（WebFetch、Kimi 天眼查 MCP 等）按清单调查 | 取决于 agent 工具 | 点名岗位 |

**CLI 不保证任何站外信息。** deepdive 只抓 BOSS 站内两页；站外调查完全在 agent 侧，结果作为 `source=agent` 的 evidence 写回。报告中标注证据等级，证据不足如实写。

机器可算信号（不需 LLM，deepdive 时随证据包输出）：BOSS 数/岗位数比、招聘者头衔类别（HR vs 业务）、岗位年龄估算、列表与详情要求差异、同公司在招工种结构（建编制 / 补漏 / 养鱼）。

## 8. CLI 命令

| 组 | 命令 | 作用 |
|---|---|---|
| 环境 | `init` | 查依赖、拉起专用 Chrome（包装上游 `--check/--setup-chrome`）、建目录与库 |
| | `status` | 岗位数、上次 run、Chrome 状态、风控冷却到几点 |
| 一层 | `scan --strategy F` | 按矩阵浅爬，写 jobs/sightings/runs |
| | `import F...` | 导入历史 JSON 为一个 run（今天 42 个文件） |
| | `deepdive JOB_ID` | 抓详情页 + 公司页，落库，打印深证据 JSON |
| 二层 | `match [--scoring F]` | 删除并重算全部 rule 便利贴 |
| | `attr set/get/list` | 便利贴读写 |
| | `report set JOB_ID F` | 存 agent 的深挖报告 |
| 三层 | `db migrate / insert T JSON / query SQL` | 扩展表建、写、只读查 |
| 展示 | `panel [--spec F] [--open]` | 通用渲染器，默认规格复刻今天两份报告 |
| 校验 | `validate {strategy,scoring,panel,schema} F` | agent 生成文件先校验再落盘 |

不设 `resume` 命令：简历建议是深挖报告第四部分。

## 9. Skill 目录

```
skill/
├── SKILL.md                    # 触发词、命令速查、五条铁律、四个工作流
├── references/
│   ├── interview.md            # 访谈脚本（8 问，含追问"能否手写代码"）
│   ├── strategy-schema.md
│   ├── scoring-schema.md       # 如何从 profile 推出规则
│   ├── report-template.md      # 判定表 + 证据链 + 直言风险，四部分
│   └── research-checklist.md   # 站外调查清单；有天眼查类工具时委托
└── examples/                   # 首个用户（作者）的四份文件
    ├── profile.chip-qc-to-aipm.json
    ├── strategy.7city-6kw.json
    ├── scoring.chip-qc-to-aipm.json
    └── panel.default.json
```

**五条铁律**：
1. 不并行扫描、不缩短 budget 等待；遇风控码立即停并告知等待时间。
2. 生成的每份 JSON 先 `validate` 再落盘。
3. deepdive 后必须 `attr set` 写回 `authentic`、`jd_translation` 并 `report set`，否则视为未完成。
4. 简历原文默认不进 LLM 上下文，只用 profile.json 结构化摘要；用户明确要求才读全文。
5. 报告用"不客气体裁"：结论后跟证据，证据不足写"证据不足"，不补脑。

**agent 的五处推理**：访谈生成 profile；从 profile 生成 scoring；从需求生成 strategy；读证据包写判定报告（真招判定 / JD 翻译 / 不匹配点 / 两版简历建议）；按需改 panel.json。

**四个工作流**：

| 场景 | 顺序 |
|---|---|
| 首次使用 | 访谈 → profile/strategy/scoring → validate → init → scan → match → panel |
| 日常扫描 | scan → match → panel |
| 点名深挖 | deepdive → 读证据 → 站外调查（清单）→ 写报告 → attr set + report set → panel |
| 记录事件 | 首次：写 schema → db migrate；之后：db insert；panel.json 加 tab |

## 10. v1 范围

**做**：第 8 节全部命令；第 9 节完整目录；`panel` 通用渲染（表格 + 柱状图）；sightings 存原始 JSON；作者四份文件作 examples；fixtures 单元测试（今天 42 个 JSON 作测试数据，打分引擎 / 校验器 / 渲染器离线可测）。

**不做（v2）**：agent 自动精修分数（v1 手动 attr set）；其他平台；Kimi 专用集成（清单里"有就用"）；表格柱状图以外的图表。

**永不做**：自动投递；多用户数据汇聚。

## 11. 工程决定

- Python ≥ 3.10，uv 管理，SQLite + JSON1，零额外服务。
- 上游 `boss-zhipin-scraper` 复制进 `vendor/` 固定版本，保留 MIT LICENSE 与 NOTICE；不用 submodule（安装绊脚石）。
- 安装：clone 进 agent 的 skills 目录 → `uv sync` → agent 读到 SKILL.md。
- 命令名 `where-my-job`，数据目录 `~/.where-my-job/`。

## 12. 错误处理

| 情况 | 行为 |
|---|---|
| 风控码 31/37 | run 标 blocked；`status` 显示冷却到几点；冷却期内 `scan` 拒绝执行 |
| Chrome 未启动 | 提示运行 `init` |
| 登录态丢失 | 提示在专用 Chrome 登录，不动主 Chrome |
| agent 生成的 JSON 不合法 | `validate` 报具体字段错误，不落盘 |
| deepdive 页面结构变化 | 原文仍落库，解析字段为空并标注，agent 可读原文 |

## 13. 测试

- 单元：scoring 引擎（用今天 402 岗验证与 score_report.py 输出一致）、strategy/scoring/schema 校验器、panel 渲染器、attr 幂等、db migrate 加列不丢数据。
- 集成（可选、需登录）：上游 `--smoke-test`；`scan` 单页；`deepdive` 单岗。
- 迁移验证：`import` 42 文件后 jobs 数 = 1225 去重、excluded 后 = 402。

## 14. 开放问题

- 列表 API 真招信号字段的确切名称与取值，首次 scan 核对后回填 scoring 示例。
- `v_jobs` 视图列名冲突处理（同 key 多来源）：暂定列名带来源后缀 `score_rule / score_agent`，另给合并列 `score`。
- 985/211 优先核验：作为 deepdive 副产品，从 JD 原文正则提取，贴 rule 便利贴。
