# 独立复核（验收方：Codex）材料与标准

验收方不参与实施，只对交付物做复核。实施由 opencode 按 `docs/superpowers/plans/` 逐任务执行；编排由 Claude 负责。验收方只写 `docs/reviews/` 与 `docs/acceptance/` 下的文件，不改源码，不运行爬虫，不访问 BOSS。

## 交付材料

1. 仓库某一提交（写明 hash），工作树干净。
2. `uv run pytest -q -m "not slow"` 完整输出（公共测试）与 `uv run pytest -m slow tests/unit/test_release_check.py -q` 输出。
3. `WMJ_PRIVATE_MANIFEST=… uv run pytest tests/regression -q` 输出（私有回归，作者机器上运行并附上；验收方不拿到私有数据）。
4. `uv run python scripts/release_check.py` 输出 JSON。
5. `docs/acceptance/YYYY-MM-DD-beta-acceptance.md`（路径 A 必填；路径 B 或未做原因）。
6. 合成 demo 生成的面板文件（路径 A 第 4 步打印的 `panel/latest.html`）。
7. 设计 v3、总索引、六份子计划、第 1 轮及之后的评审记录，用于对照。

## 通过标准

| 项 | 标准 |
|---|---|
| 测试 | 公共测试 0 失败；私有回归 1260 observations / 1225 jobs / 重导 0 新增 / 34 个多命中岗位；legacy 402 与分布 S3/A41/B77/C119/D162；handoff-intent 478、差异 76 |
| 契约 | 任意 cwd 调用；stdout 单行 JSON；退出码 0–4 各有覆盖用例；输出无 `security_id`/`lid`/`encrypt_boss_id`/`raw_json` |
| 存储 | 15 表 + 4 视图与设计 v3 §4 一致；`data delete --all` 不动 `network_policy_state` |
| 规则 | AST 三值传播用例；campus_policy 四种输入推导；技能 cap |
| 事件流 | 首次 applied 建身份；同键重试返回原 ID；纠错链；升版兼容/不兼容；删除不误伤；事件文档示例经真实 service 往返 |
| 证据/报告 | 两侧皆空必须"证据不足"；acquisition_state 不因报告改变；`evidence show` 无私有字段 |
| 网络门禁（离线） | 第二页 31/37/验证码/空/未知码；84 页拒绝；跨 run 累计；锁占用；非回环拒绝 |
| 在线开关 | 默认禁用时 scan、非缓存 deepdive、`init --browser`、`init --probe` 退出 2 `ONLINE_DISABLED` 且未创建 launcher/transport；`scan --dry-run`、`deepdive --cached`、`browser stop` 可用 |
| 面板安全 | 恶意文本、闭合标签、`javascript:`、原始 HTML、超长正则用例通过；无外部资源 |
| 发行 | `release_check.py` findings 为空且匹配值均为 `<redacted>`；sdist/wheel 每个成员路径、类型、必要文件与内容检查通过；examples 全通过校验；references 每个示例块通过 schema |
| 文档 | SKILL.md 行内命令都能在解析器找到；SKILL.md、README、验收模板的 demo 命令块逐字一致；README 状态行与 `release.py` 一致；SKILL.md 与示例不出现冻结历史输入 |
| 验收记录 | 路径 A ≤ 30 分钟且有逐步计时；导入 5 条观察 / 4 个岗位、重导新增 0、面板标题含"合成数据演示"；非作者试用有记录 |

## 不通过即阻塞

- 任何测试失败；任何 `release_check.py` finding；公开树出现真实岗位/公司/个人数据。
- README 说"已通过"但 `release.py` 仍 disabled，或反之。
- 面板注入用例任一失败。
- 设计 v3 明确"不做"的能力出现在代码里（自由 SQL、`x_` 表、真招概率、自动清理、自动投递）。

## 验收方不做

不改源码；不联网核验平台；不生成真实数据；不以"能打开面板"或"格式校验通过"代替对招聘结论真实性的判断。

## 输出

`docs/reviews/YYYY-MM-DD-acceptance-codex.md`：逐项通过/不通过 + 证据引用 + 阻塞清单。阻塞项回到 opencode 修复，修复后重新提交同一材料清单。
