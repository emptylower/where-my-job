# 首次使用

两条路径分别计时，互不混淆。命令都由 agent 在对话中运行，这里列出来供核对。

## 路径 A：合成 demo（不碰你的真实数据，不需要联网）

demo 使用新的临时数据目录，不覆盖你已有的配置与数据库。仓库默认安装位置为 `~/where-my-job`，其它位置只改第一行。

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

面板标题显示"合成数据演示"。导入应得到 5 条观察、4 个岗位；再导入同两份文件新增 0 条。


## 路径 B：你本人的真实单页（需要联网，且发布门槛已通过）

在新终端里操作（或先 `unset WMJ_HOME`），不要沿用 demo 的临时目录，也不要把 demo 的合成画像当成你的画像。

```bash
where-my-job init
where-my-job login start             # 专用 Chrome 打开登录页，二维码直接画在这条命令的输出里（约 30 秒换一张）
where-my-job login status --wait 30  # 你用 BOSS 直聘 App 扫码确认；agent 重复运行直到 status 为 confirmed
where-my-job scan --strategy ~/where-my-job/skill/examples/strategy.first-page.json --dry-run
where-my-job scan --strategy ~/where-my-job/skill/examples/strategy.first-page.json
where-my-job match && where-my-job panel --open
where-my-job browser stop
```

不想扫码时，可以 `where-my-job init --browser` 后在专用 Chrome 里手动登录。

