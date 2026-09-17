<!-- tests/manual/ONLINE_CHECKLIST.md -->
# 在线真实核验清单（D16–D18）

**本清单不作为 CI，不进入自动测试，不在无人值守环境执行。** 自动测试全部离线；本清单只在满足发布门槛时，由维护者本人在自己的专用 Chrome 中手动执行一次，结果写入 `docs/reviews/online-check-<日期>.md`。任一必查项未通过，在线适配器保持 disabled，交付禁用在线适配器的离线 beta。

## 0. 发布门槛（任一不满足即停止）

- [ ] 维护者已核对 BOSS 当时的用户协议与允许范围，记录日期、条款位置与本工具边界（设计 v3 §2、§14）。
- [ ] 使用维护者本人账号、本人正常求职查看范围；不使用他人账号，不批量、不并行。
- [ ] `uv run pytest -q -m "not perf"` 全绿，含 `tests/security/test_risk_matrix.py`。
- [ ] `where-my-job status` 的 `network.cooldown_until` 为空。

## 1. 环境

| 项 | 记录 |
|---|---|
| 日期时间（本地/UTC） | |
| macOS 版本 | `sw_vers` |
| Chrome 版本 | `/json/version` 的 `Browser` |
| where-my-job 版本与 git commit | `where-my-job --version`、`git rev-parse HEAD` |
| vendor 上游 commit | `eb5a8e646d4e4bfc024cf53f2a5b543ad8d75edc` |

## 2. 启动、监听与空白重启

1. `where-my-job init --browser`，在弹出的专用 Chrome 中手动登录。
2. `lsof -nP -iTCP:9222 -sTCP:LISTEN`。**通过：** 只出现 `127.0.0.1:9222` 或 `[::1]:9222`。
3. `ps -o command= -p <pid>`。**通过：** 含 `--user-data-dir=<WMJ_HOME>/browser-profile` 与 `about:blank`，不含 `--remote-allow-origins`。
4. 从局域网另一台设备访问 `http://<本机IP>:9222/json/version`。**通过：** 连接失败。
5. **空白重启（正常退出）：** 在专用 Chrome 中打开任意 zhipin.com 页面，运行 `where-my-job browser stop`，再运行 `init --browser`。**通过：** 只有 `about:blank` 页；随后 `init --probe` 不因恢复标签页报 `BROWSER_NOT_BLANK`。（2026-09-16 已在隔离 profile、隔离端口上以相同启动参数验证：SIGTERM 与 SIGKILL 两种退出方式重开后都只有 `about:blank`。）
6. **空白重启（异常退出）：** 打开 zhipin.com 页面后 `kill -9 <pid>`，再 `init --browser`。**通过：** 不恢复旧标签页；若恢复了，`init --probe` 必须以 `BROWSER_NOT_BLANK` 拒绝、不计动作、不建 run。任一情况不满足则在线适配器保持 disabled。

## 2b. 扫码登录（agent 驱动）

由 agent 运行命令，维护者只在手机上扫码确认。登录前先打开 BOSS 直聘 App 的扫一扫。

1. `where-my-job login start`。**通过：** 退出 0；`data.login.status` 为 `waiting_scan` 或 `qr_not_found`；`qr_png` 文件权限 0600；`waiting_scan` 时 stderr 有一行扫码提示和字符画二维码，stdout 与 stderr 不含二维码原文；专用 Chrome 只多出一个登录页标签。
2. 维护者按 ctrl+o 展开这条命令的输出，用 BOSS 直聘 App 扫字符画二维码并确认；agent 循环运行 `where-my-job login status --wait 30`。**通过：** 最终 `status=confirmed`；登录页被关闭；`state/login.json` 与 `state/login-qr.png` 已删除。扫之前先用 `where-my-job login test-qr` 验一次显示，记录用的是深色还是浅色画法（`--light-terminal`）。
3. 随后 `where-my-job init --probe`。**通过：** `data.probe.login=available`。
4. 记录：登录页默认是否直接显示二维码；二维码是否被识别；字符画能否直接扫出、终端背景深浅；页面自行换码的间隔（观察 `qr_updated` 且 `refreshes` 不变）；刷新次数（`refreshes`）与 `data.login.notes` 里的 `expiry_marker:`；从 `login start` 到 `confirmed` 的耗时；是否出现验证码或站外文档拦截。出现 `qr_not_found` 时写明页面实际显示内容，交回 `adapter/login.py` 离线修正，不在现场改代码继续试。

## 3. Document 拦截（R2 必查）

实现只对 `Fetch.enable` 的 `resourceType=Document, requestStage=Request` 拦截，允许项以不带修改的 `Fetch.continueRequest` 放行，拒绝项以 `Fetch.failRequest(errorReason="BlockedByClient")` 拒绝。拦截是否改变平台风控表现未经核验。

拦截的判定分三类，核验时都要记录：平台在一次导航里插入的同站中间跳（例如 `/web/passport/zp/security.html`）会被放行，最终地址必须落回期望页；最终停在 `/web/passport/zp/` 家族按风控处理（退出 3 + 冷却），停在站内其它页面按落点不符失败（退出 2）；站外文档与登录页、验证页仍然一律拒绝，其中站外子文档（`sub:unknown:` 开头，计入 `refused_subframes`）是设计内行为，页面继续，不算失败。

- [ ] 在拦截开启的状态下完成第 4 节的一页列表：记录是否出现验证码、31/37、限制访问页。
- [ ] 若出现任何风控表现，立即停止，在线适配器保持 disabled。**不允许以删除拦截作为修复**；把现象写入记录，回到离线设计评审。

## 4. 一页列表

1. `where-my-job scan --strategy <首次单页策略> --dry-run`，确认 `planned_actions == 1`，前后数据目录无变化。
2. 去掉 `--dry-run` 执行。
3. **通过：** 退出 0；`job list` 出现本页岗位；`sightings.raw_kind='api_entry'`；envelope 与面板无 `securityId`/`lid`。
4. 记录：捕获是否绑定本次导航（loaderId 一致）、`hasMore` 原值、条目数、耗时；前台标签页下滚动翻页是否触发下一页请求。
- **落点路径复核（2026-09-16 提出，同日结案）：** 登录后的第一次探测落在 `/web/geek/jobs`（复数），查询参数只有 `city`、`page`、`query`，没有 `_security_check`——平台确实把搜索列表页改了名，`_security_check` 只是未登录时的附加标记。子计划 13 已让两种拼法互认（`same_document`），`ALLOWED_URL` 不变（工具仍只请求单数地址，跟随平台自己的跳转）。
- **改名之后的复核（子计划 13 提出，2026-09-16 第六次核验部分回答）：** 改名后的列表页**仍然调** `/wapi/zpgeek/search/joblist.json`（端点没变），但查询参数与本工具的期望不符（`ignored_reasons: {"other_parameters": 1}`）。同一地址的人工视角正常显示岗位列表且已登录，因此页面与登录态都不是原因。
- **第七次核验的答案（2026-09-16）：** `params:query=missing,city=missing,page=missing`、地址 `?[_]`——整套搜索参数不在 URL 上。同日第三次只读观察未能查明参数去向：**附加 CDP 会话后页面会主动置空自己**（反调试签名，还尝试了 `window.close()`），观察记录见 `docs/reviews/online-check-2026-09-16.md`。
- **第十次核验与根因（2026-09-16）：** 维护者目视确认专用 Chrome 里页面先正常渲染出岗位列表、随后被跳成空白页；工具侧表现为 `body_unavailable`。逐字比对上游爬虫：它**从不启用 Fetch**，源码里连 `passport/security.html` 都没出现过。推断是本工具的文档拦截打断了平台带一次性令牌的登录握手。子计划 17 据此把拦截改成开关：只在本工具自己的导航与登录流程期间开着，列表页提交且落点复核通过之后关闭，此后只旁听。
- **第十一次核验（2026-09-16，子计划 17 之后）：** `body:success,items=15,code=0,has_more=true`——**平台照常返回岗位列表**；无 `saw:` 行，页面不再跳握手页。唯一不符的是查询参数：地址里只剩防缓存参数 `_`，平台已把搜索条件移出接口地址。`other_parameters` 这个码本身证明会话、文档、顺序、端点四项都已通过。子计划 18 据此把参数判定改为"带了就必须一致，一个都没带就按文档与顺序绑定"，并记 `bound:document_only`。
- **第一次真实 deepdive（2026-09-17）：** 详情页与公司页在文档拦截全程开启的情况下**跑通了**，`errors` 为空，没有 `document_changed`，也没有出现 `passport/zp/security.html` 握手。这推翻了"拦截必然打断页面"的预判，但**只证明跑通一次，未证明稳定**——第 8/9 次探测里的握手出现在扫码登录后的首次列表导航上，本次登录态新鲜、握手没有重现。登录态临近过期时再跑 deepdive，仍可能撞上同一问题。
- **公司页两个计数读反了（2026-09-17）：** 平台把数字写在标签**前面**、两个数连写在页头一行（格式为"<岗位数>在招职位<BOSS数>位BOSS"）。旧正则假设数字在标签后面，于是 `job_count` 抓到的其实是 BOSS 数（**错值，静默通过**），`boss_count` 抓不到（记 unknown，把整份证据判成 partial）。**被告警的字段无关紧要，静默通过的字段是错的。** 子计划 19 改为两个数整体锚定、匹配不上就两个都记 unknown，并让这两个附属计数不再决定 `completeness`。
- **由此确立的方法论：** 凡是用正则从页面文本抽取的字段，在**拿真实页面核对过之前一律不可信**。它们不是"匹配不到就 unknown"那么温和，而是**可能匹配到错的东西并且静默通过**。合成夹具无法发现这类问题——夹具和正则出自同一个猜测，测试只能证明两者一致，不能证明任何一方与平台一致。每新增一个此类字段，都必须在在线核查里用真实页面对一次，并把对照结果记在本文件。
- **证据原文含使用者姓名（2026-09-17）：** 公司页 `page_text` 取自 `document.body.innerText`，包含登录态页头，里面有使用者本人的姓名。证据原文**只留在本地数据库**，不得导出进任何公开制品，也不得用作测试夹具；所有夹具一律合成。
- **空白页的解释（2026-09-16）：** 动作结束时 `CdpTransport.close()` 会 `Target.closeTarget` 关掉本工具新建的标签页，窗口里剩下的正是 `init --browser` 留下的 `about:blank`；早期几次看到的"跳转后空白"则是被拦掉的文档留下的 `chrome-error://chromewebdata/`。**都是本工具自己的行为，不是平台在销毁页面。** 核验时若要确认，看标签页是消失还是被改址。
- **拦截关闭后交换掉的东西（核验时要一并观察）：** 站外子文档（广告、埋点 iframe）不再被拦，`refused_subframes` 基本恒为 0；页面在提交之后跳到验证页时那个页面会被加载，然后才按落点判定停机（退出 3 + 冷却 + 不入库不变）；诊断来源从拦截记录（`main:`/`sub:`）变成观察记录（`saw:`）。登录流程与详情页仍全程拦截。
- **下一次只读一行（仍是子计划 15 的判据）：** `data.documents` 里的 `body:` 行。`items` 大于 0 说明平台照常返回了岗位、问题只在绑定；`items=0` 说明页面确实被限制，采集这条路到头，转向导入路径。同时记录 `hop:` 行有几条（正常应为两条：握手页 + 跳回期望页）。**不要做任何规避检测的改动。**
- **登录态的已知缺陷（2026-09-16 实测）：** `browser stop` → `init --browser` 之后登录态必然失效（cookie 库里 `zp_at`/`bst`/`wt2`/`wbg` 全部消失）。因此 `BROWSER_NOT_BLANK` 的处置办法会顺带把登录冲掉，核验时要把"重新扫码登录"算进步骤，不要以为关掉重开不影响登录。

## 5. 一个详情页与一个公司页

1. 选一个有公司 ID 的岗位：`where-my-job deepdive <job_id>`。
2. **通过：** 退出 0 或 4；两条 `origin=cli` 证据；详情证据 JD 不含登录墙或安全提示文本；`ld_upDate_raw` 与公司页计数原值被原样记录或明确为 unknown。
3. 两次 evaluate 返回的 URL 一致；不一致即记录并停止。选择器或计数正则不匹配时写明页面实际文案，交回 `adapter/detail.py` 离线修正，不在现场改代码继续试。

## 6. 停止条件（出现任一立即停止，不重试、不换关键词再试）

- 任一命令退出 3（`RISK_DETECTED` / `COOLDOWN_ACTIVE` / `BUDGET_EXHAUSTED` / `RESOURCE_BUSY` / `CLOCK_ANOMALY`）。
- 页面出现验证码、安全验证、限制访问提示，或跳转到登录页。
- 捕获超时或未知响应（退出 2/4），先离线复现。
- 本清单累计超过 11 次受控动作（扫码登录 1 次 + 至多 6 次二维码刷新 + 探测 1 次 + 一页列表 1 次 + 详情与公司页 2 次）。

**不主动制造风控**：不为验证 31/37 路径而加速、并行或重复请求；风控路径只用离线 fixtures 验证。

## 7. 记录模板

```text
日期：
执行人：
发布门槛：协议核对 [是/否]（条款位置：        ）  离线测试全绿 [是/否]  冷却为空 [是/否]
监听：lsof 输出摘要：                局域网访问失败 [是/否]
空白重启：正常退出 [通过/未通过]  异常退出 [通过/未通过]
浏览器里有别的标签页时：错误码 [BROWSER_NOT_BLANK/其它]  消耗动作 [是/否]  建 run [是/否]
扫码登录：start 退出码   status 序列   刷新次数   耗时（秒）   默认显示二维码 [是/否]   qr_not_found [是/否]   字符画可扫 [是/否]   终端背景 [深/浅]   二维码有效秒数
Document 拦截：风控表现 [无/有：        ]
一页列表：退出码   条目数   hasMore   loaderId 绑定 [是/否]   私有字段未外露 [是/否]   refused_subframes 次数   data.documents 摘要
详情页：退出码   completeness   JD 长度   两次 URL 一致 [是/否]
公司页：completeness   job_count_raw   boss_count_raw   未识别项：
动作总数：    冷却触发 [是/否]（若是：原因码/时间）
结论：在线适配器 [启用/保持 disabled]   理由：
```
