# 输入协议参考

字段来源：随包 JSON Schema；本文件与示例必须一同校验。

## evidence

origin 可在输入文件声明，但须与 --origin 一致；命令默认 agent，用户来源使用 --origin user，不可自报 cli。时间必须能解析为带时区的真实时间；published_at 未知可省略，不猜测零点。证据必须属于指定岗位或已核实公司。结构字段经过公开白名单；完整原文只经 --local-out 写本地文件，stdout 只返回标识、路径与状态。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.job_id` (`job_id`) | 否 | {"type": "string", "pattern": "^boss:[A-Za-z0-9~_-]{1,128}$"} |
| `$.company_id` (`company_id`) | 否 | {"type": "string", "pattern": "^boss:[A-Za-z0-9~_-]{1,128}$"} |
| `$.kind` (`kind`) | 是 | {"enum": ["web_page", "document", "user_statement"]} |
| `$.origin` (`origin`) | 否 | {"enum": ["agent", "user"]} |
| `$.url` (`url`) | 否 | {"type": "string", "maxLength": 2048, "pattern": "^https://[^\\s]+$"} |
| `$.captured_at` (`captured_at`) | 是 | {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z&#124;[+-]\\d{2}:\\d{2})$"} |
| `$.published_at` (`published_at`) | 否 | {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z&#124;[+-]\\d{2}:\\d{2})$"} |
| `$.excerpt` (`excerpt`) | 是 | {"type": "string", "minLength": 1, "maxLength": 262144} |
| `$.full_text` (`full_text`) | 否 | {"type": "string", "maxLength": 262144} |
| `$.structured` (`structured`) | 否 | {"type": "object"} |
| `$.source_note` (`source_note`) | 否 | {"type": "string", "maxLength": 1024} |
| `$.idempotency_key` (`idempotency_key`) | 是 | {"type": "string", "minLength": 8, "maxLength": 200} |

含条件分支的必填名称：`captured_at`、`company_id`、`excerpt`、`idempotency_key`、`job_id`、`kind`、`schema_version`。

<!-- schema: evidence -->
```json
{
  "schema_version": 1,
  "job_id": "boss:SYN0001aaaa",
  "kind": "web_page",
  "origin": "agent",
  "url": "https://example.com/careers/ai-pm",
  "captured_at": "2026-09-14T10:00:00Z",
  "excerpt": "合成页面文字：AI 产品岗位。",
  "structured": {},
  "source_note": "合成示例，不代表已访问网页。",
  "idempotency_key": "evidence-synthetic-0001"
}
```

## report

四个必需标题为：## 招聘信号判断、## JD 翻译、## 不匹配点、## 简历建议，均需非空。事实、信号引用 evidence_id；JD/不匹配项提供 evidence_id 或非空 assumption。引用必须在绑定基础包与声明补充证据的闭包内。两侧皆空必须证据不足；没有反对线索不代表反对证据不存在。报告完成不改变 acquisition_state。示例 ID 是固定合成验证用值，真实提交须来自已保存的 bundle/evidence。第二版简历建议是待做行动。

| 路径 | 必填 | 约束 |
|---|---|---|
| `$.schema_version` (`schema_version`) | 是 | {"const": 1} |
| `$.job_id` (`job_id`) | 是 | {"type": "string", "pattern": "^boss:[A-Za-z0-9~_-]{1,128}$"} |
| `$.bundle_id` (`bundle_id`) | 是 | {"type": "string", "minLength": 1, "maxLength": 200} |
| `$.extra_evidence_ids` (`extra_evidence_ids`) | 否 | {"type": "array", "maxItems": 200} |
| `$.profile_revision` (`profile_revision`) | 是 | {"type": "string", "minLength": 1, "maxLength": 200} |
| `$.idempotency_key` (`idempotency_key`) | 是 | {"type": "string", "minLength": 8, "maxLength": 200} |
| `$.authentic` (`authentic`) | 是 | {"type": "object"} |
| `$.authentic.facts` (`facts`) | 是 | {"type": "array"} |
| `$.authentic.supporting` (`supporting`) | 是 | {"type": "array"} |
| `$.authentic.opposing` (`opposing`) | 是 | {"type": "array"} |
| `$.authentic.unknowns` (`unknowns`) | 是 | {"type": "array"} |
| `$.authentic.conclusion` (`conclusion`) | 是 | {"enum": ["倾向真实在招", "倾向长期挂岗", "证据不足"]} |
| `$.authentic.conclusion_label` (`conclusion_label`) | 是 | {"const": "推断"} |
| `$.jd_translation` (`jd_translation`) | 是 | {"type": "object"} |
| `$.jd_translation.sentences` (`sentences`) | 是 | {"type": "array"} |
| `$.mismatches` (`mismatches`) | 是 | {"type": "array"} |
| `$.resume_advice` (`resume_advice`) | 是 | {"type": "object"} |
| `$.resume_advice.proven` (`proven`) | 是 | {"type": "array"} |
| `$.resume_advice.to_reach` (`to_reach`) | 是 | {"type": "array"} |
| `$.report_md` (`report_md`) | 是 | {"type": "string", "minLength": 1, "maxLength": 262144} |
| `#/$defs/ref_claim.evidence_id` (`evidence_id`) | 是 | {"type": "string", "minLength": 1, "maxLength": 200} |
| `#/$defs/ref_claim.claim` (`claim`) | 是 | {"type": "string", "minLength": 1, "maxLength": 2000} |
| `#/$defs/sentence.original` (`original`) | 是 | {"type": "string", "minLength": 1, "maxLength": 4000} |
| `#/$defs/sentence.explanation` (`explanation`) | 是 | {"type": "string", "minLength": 1, "maxLength": 4000} |
| `#/$defs/sentence.evidence_id` (`evidence_id`) | 否 | {"type": "string", "minLength": 1, "maxLength": 200} |
| `#/$defs/sentence.assumption` (`assumption`) | 否 | {"type": "string", "minLength": 1, "maxLength": 2000} |
| `#/$defs/mismatch.requirement` (`requirement`) | 是 | {"type": "string", "minLength": 1, "maxLength": 2000} |
| `#/$defs/mismatch.profile` (`profile`) | 是 | {"type": "string", "minLength": 1, "maxLength": 2000} |
| `#/$defs/mismatch.severity` (`severity`) | 是 | {"enum": ["high", "medium", "low", "unknown"]} |
| `#/$defs/mismatch.evidence_id` (`evidence_id`) | 否 | {"type": "string", "minLength": 1, "maxLength": 200} |
| `#/$defs/mismatch.assumption` (`assumption`) | 否 | {"type": "string", "minLength": 1, "maxLength": 2000} |

含条件分支的必填名称：`assumption`、`authentic`、`bundle_id`、`claim`、`conclusion`、`conclusion_label`、`evidence_id`、`explanation`、`facts`、`idempotency_key`、`jd_translation`、`job_id`、`mismatches`、`opposing`、`original`、`profile`、`profile_revision`、`proven`、`report_md`、`requirement`、`resume_advice`、`schema_version`、`sentences`、`severity`、`supporting`、`to_reach`、`unknowns`。

<!-- schema: report -->
```json
{
  "schema_version": 1,
  "job_id": "boss:SYN0001aaaa",
  "bundle_id": "bundle_SYN0001",
  "extra_evidence_ids": [],
  "profile_revision": "synthetic-qc-to-aipm-v1",
  "idempotency_key": "report-synthetic-0001",
  "authentic": {
    "facts": [
      {
        "evidence_id": "ev_SYN0001detail",
        "claim": "合成 JD 提及 Agent 工具。"
      }
    ],
    "supporting": [],
    "opposing": [],
    "unknowns": [
      "未取得可判断当前招聘意向或长期展示的线索；合成 JD 不代表真实招聘。"
    ],
    "conclusion": "证据不足",
    "conclusion_label": "推断"
  },
  "jd_translation": {
    "sentences": [
      {
        "original": "熟悉 Agent 工作流",
        "explanation": "需要理解工具之间的任务衔接。",
        "assumption": "是否要求编写代码尚未说明。",
        "evidence_id": "ev_SYN0001detail"
      }
    ]
  },
  "mismatches": [
    {
      "requirement": "岗位具体产品经验要求待核验",
      "profile": "画像只提供了 QC 流程经历",
      "severity": "unknown",
      "assumption": "尚未取得可确认经验门槛的 JD 原句。"
    }
  ],
  "resume_advice": {
    "proven": [
      "按画像自述说明 QC 工作中的需求拆解和验收职责。"
    ],
    "to_reach": [
      "补充可演示的 AI 工具项目并记录验证过程。"
    ]
  },
  "report_md": "# 合成岗位报告\n\n## 招聘信号判断\n事实：合成 JD 提及 Agent 工具（ev_SYN0001detail）。\n支持信号：未取得。反对信号：未取得。\n未知：当前招聘意向及展示持续性均未核验。定性倾向：证据不足（推断）。\n没有连续采样，不能从离散观察推断持续展示或持续招聘。\n\n## JD 翻译\n熟悉 Agent 工作流：需要理解工具间任务衔接（ev_SYN0001detail）；是否要求编写代码未知。\n\n## 不匹配点\n产品经验门槛未知；画像只提供 QC 经历，不推断已满足产品岗位要求。\n\n## 简历建议\n已证实经历如何表达：按画像自述说明需求拆解与验收职责。\n要达标还需补的行动：制作可演示项目并记录验证过程，不写成已有经历。\n"
}
```

