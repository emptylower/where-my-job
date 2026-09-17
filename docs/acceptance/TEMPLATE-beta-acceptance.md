# beta 验收记录（复制为 `YYYY-MM-DD-beta-acceptance.md` 填写）

日期：____ · 验收人：____（作者 / 非作者）· 机器：macOS __ · Chrome __ · Python __ · uv __ · 提交：____

## 路径 A：粘贴开场 prompt → 合成 demo 面板（目标 ≤ 30 分钟）

从在 agent 对话框粘贴 README「用 agent 开始」里的开场 prompt 开始计时。验收人不手动执行命令，所有命令由 agent 运行；agent 可以用 `bash scripts/acceptance_timer.sh <命令>` 记录每步耗时。下面整段是 agent 应运行的合成 demo 命令，供核对 agent 的实际操作。仓库默认安装位置为 `~/where-my-job`，其它安装位置只修改第一行。

```bash
set -e
WMJ_DEMO_REPO="$HOME/where-my-job"
WMJ="where-my-job"        # 开发态改成：WMJ="uv run --project $WMJ_DEMO_REPO where-my-job"
export WMJ_HOME="$(mktemp -d "${TMPDIR:-/tmp}/wmj-demo.XXXXXX")"
$WMJ init
$WMJ validate profile "$WMJ_DEMO_REPO/skill/examples/profile.synthetic-qc-to-aipm.json"
$WMJ validate scoring "$WMJ_DEMO_REPO/skill/examples/scoring.minimal-aipm.json"
$WMJ validate panel "$WMJ_DEMO_REPO/skill/examples/panel.default.json"
install -m 600 "$WMJ_DEMO_REPO/skill/examples/profile.synthetic-qc-to-aipm.json" "$WMJ_HOME/profile.json"
install -m 600 "$WMJ_DEMO_REPO/skill/examples/scoring.minimal-aipm.json" "$WMJ_HOME/scoring.json"
install -m 600 "$WMJ_DEMO_REPO/skill/examples/panel.default.json" "$WMJ_HOME/panel.json"
$WMJ import "$WMJ_DEMO_REPO/tests/fixtures/synthetic/legacy/合肥_AI产品经理.json" "$WMJ_DEMO_REPO/tests/fixtures/synthetic/legacy/合肥_产品经理.json"
$WMJ match
$WMJ panel --open
printf '合成演示数据目录：%s\n面板：%s/panel/latest.html\n' "$WMJ_HOME" "$WMJ_HOME"
```

| 步骤 | agent 做了什么 | 耗时（秒） | 退出码 | 人工干预 | 备注 |
|---|---|---|---|---|---|
| 1 | 检查或安装 uv | | | 安装前是否征得同意 | |
| 2 | 克隆到 `~/where-my-job`、`uv tool install ~/where-my-job`、`where-my-job version` | | | PATH 是否需处理 | |
| 3 | 链接 `~/.claude/skills/where-my-job` | | | | |
| 4 | 运行上面整段 demo 命令 | | | | import 输出 `observations_inserted=5`、`jobs_total=4` |
| 5 | 用第 4 步打印的目录再导入同两份文件 | | | | `observations_inserted=0` |
| 6 | 目检打开的面板 | | | 标题是否含"合成数据演示" | |
| 合计 | | | | | ≤ 30 分钟 → 通过 |

## 路径 B：同一对话中完成本人真实单页面板（另计时；仅当联网门槛已通过且验收人自愿）

在同一 agent 对话里继续，命令由 agent 运行；不设置 `WMJ_HOME` 或设为验收人明确选择的专用目录；不沿用路径 A 的临时目录与合成画像。

| 步骤 | 命令（agent 运行） | 耗时（秒） | 退出码 | 备注 |
|---|---|---|---|---|
| 1 | `where-my-job login start` → 验收人展开命令输出扫字符画二维码（或扫专用 Chrome 窗口）→ 循环 `where-my-job login status --wait 30` | | | 登录耗时单列：____ 秒；刷新次数：____；字符画可扫：是 / 否；失败原因：____ |
| 2 | `where-my-job scan --strategy … --dry-run` | | | planned_actions=1 |
| 3 | `where-my-job scan --strategy …` | | | 退出 0/3/4 各是什么含义已向验收人说明 |
| 4 | `where-my-job match && where-my-job panel --open` | | | |
| 5 | `where-my-job browser stop` | | | |

未做路径 B 的原因（门槛未通过 / 验收人不联网 / 平台不可用）：____

## 非作者试用

角色：____ · 是否看过设计文档：否 · 卡住的地方与用了多久解决：

1. ____
2. ____

能否指出一条排除理由并改 scoring 后重算（`match`）：是 / 否 · 备注：____

## 联网门槛核对

| 项 | 证据 | 结论 |
|---|---|---|
| 平台条款核对 | 核对日期 ____；条款编号/原文摘录 ____；本工具边界说明 ____ | 通过 / 未通过 |
| 受支持环境真实安装 | 本记录路径 A | |
| 一页列表 + 一个详情 + 一个公司页采集 | run_id ____；`status` 输出粘贴 | |
| 停机路径 | 离线用例通过（`tests/security/test_risk_matrix.py`、`tests/integration/test_scan_cmd.py`）；真实风控不主动制造 | |
| 监听地址与 profile 归属 | launcher 离线测试通过；人工核验 `lsof -nP -a -p <pid> -iTCP -sTCP:LISTEN -F pn` 输出只含回环地址 | |
| 浏览器里有别的标签页时的拒绝 | 错误码为 `BROWSER_NOT_BLANK`；不消耗动作、不建 run；按提示 `browser stop` 后重试成功 | |
| Document 拦截对平台风控表现的影响 | 人工核验记录：____；出现风控则保持禁用，不以删除拦截作为修复 | |

任一项未通过 → 发布"禁用在线适配器的离线 beta"：`src/where_my_job/release.py` 保持 `ONLINE_ADAPTER_DEFAULT = "disabled"`，README 状态行保持"未通过（日期）"。

## 结论

- 阻塞项：____（必须为空才能发布）
- 非阻塞项（记入 v1.1）：____
- 发布形态：离线 beta / 含在线适配器的 beta
- 版本号与标签：____
