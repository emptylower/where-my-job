# 隐私与处理边界

这份文档说明 CLI 承诺什么、不承诺什么，以及 agent 该守什么。措辞可以直接引用给用户。

## CLI 承诺（只对经它接口的行为）

- 不调用任何模型，不管理 API key，不回调 agent，采集循环里没有 LLM。
- 只读写数据目录（默认 `~/.where-my-job/`，或 `WMJ_HOME`）；不读主浏览器 Cookie；专用 Chrome profile 在 `browser-profile/`，`data delete --all` 也不动它。
- 私有原文（`sightings.raw_json`、证据 `full_text`）不出现在任何视图、面板和默认 stdout；只有 `evidence show ID --local-out F` 会把完整原文写到用户指定的本地文件，stdout 只返回证据 ID、路径与原文状态。受保护目录（源码、凭证目录、专用浏览器目录、数据库与锁）拒绝作为输出目标。
- 不自动读取、索引、外发 `resume/` 里的文件。
- 面板 `panel/latest.html` 不含 raw、不含 profile 全文、不含外部脚本与外部资源。
- 留存默认不过期；用户可以 `data delete --job ID`、`data delete --all`、`data prune --raw-before T` 手动清理；清理同时让本工具登记过的面板与迁移备份失效。清理不重置风控状态。

## CLI 不承诺

- 不能约束拥有同一用户 shell 权限的 agent 或其他程序去直接读数据库文件、浏览器目录或本地文件。
- 不能抹除用户手工复制、云端会话、操作系统快照里的历史副本。
- 不能证明自然语言报告里的引用真的支持结论。
- 本地存储位置不等于合规；平台条款、个人信息保护义务需要用户与发布负责人自行判断。

## agent 必须遵守

- 访谈前告知：你的内容会进入 agent 的模型提供商处理流程；这是 agent 运行环境决定的。
- 只收本次需要的信息。简历只读用户明确交给你的文件，读之前说明简历内容会进入模型提供商的处理流程；联系方式、证件号、住址不写进画像。不获取 Cookie，不读私有原文。
- 证据包（`deepdive` 返回的内容）默认不含 raw、`security_id`/`lid`、招聘者标识、profile 全文；不要试图从其他路径补齐这些字段。
- 用户已经交给你的信息，不要再承诺"仍仅在本地"。

## 扫码登录

- `where-my-job login start` 只让专用 Chrome 打开固定登录页 `https://www.zhipin.com/web/user/`，计 1 次受控动作。登录页大约每 30 秒自己换一张二维码，本工具不介入；只有截图里已经识别不到二维码、且页面明确写着二维码失效时，`login status` 才点击页面上的刷新，每次刷新再计 1 次，同一次登录最多刷新 6 次，整个登录会话最长 10 分钟。
- CLI 从页面截图里识别二维码，按原内容重新生成两份：PNG 写到数据目录 `state/login-qr.png`（权限 0600），登录完成、取消、超时或触发风控时删除；一行扫码提示和字符画写到这条命令的 stderr，供 agent 界面的命令输出区直接显示。二维码原文不以文本形式写入 stdout、stderr、数据库或日志。
- 命令输出会进入 agent 的上下文，所以二维码字符画会经过 agent 的运行环境、可能进入模型提供商的处理流程。二维码约 30 秒失效；有效期内谁用自己的 App 扫码确认，专用浏览器就登录到谁的账号，所以只给用户本人看。用户不接受时改用 `where-my-job init --browser`，在专用 Chrome 里手动登录，二维码不经过 agent。
- CLI 不读取 Cookie，不自己发请求；登录由页面自己完成。两次 `login status` 之间登录页保持打开，这期间页面不受 CLI 的文档拦截，与用户在专用 Chrome 里手动登录相同。
- 登录完成后 CLI 关闭登录页；用户放弃登录时运行 `where-my-job login cancel`。
- 采集失败时，CLI 会把被拒绝或被跳转的文档地址记进运行摘要与命令输出，只记地址的主机、路径与查询参数名，不记参数值（`lid`、`securityId` 等只出现参数名）。这些记录会随命令输出进入 agent 的上下文。

## 需要更强隔离时

由 agent 运行时配置能力限制（禁止直接网络访问、禁止读 `browser-profile/` 与 `resume/`、禁止执行 `src/where_my_job/vendor/`）。这是运行环境的职责，SKILL.md 无法自动实现。
