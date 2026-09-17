# 在线功能发布门槛

在线功能发布门槛状态：未通过（2026-09-14）

当前发布的是**禁用在线适配器的离线 beta**：采集类命令返回退出码 2 `ONLINE_DISABLED`，导入、匹配、面板、证据、报告、事件全部可用。

## 门槛细则

受影响的命令：`scan`（非 `--dry-run`）、`deepdive`（非 `--cached`）、`init --browser`、`init --probe`、`login start`、`login status`。`browser stop` 与 `login cancel` **不受**该开关影响，始终可以通过归属校验关闭本工具启动的专用浏览器或登录页。

门槛项：平台条款核对记录、受支持环境真实安装记录、一页列表 + 一个详情 + 一个公司页的采集核验、停机路径核验、Document 拦截是否改变平台风控表现的人工核验。通过后把状态行改成 `已通过（日期）`，并把 `src/where_my_job/release.py` 的 `ONLINE_ADAPTER_DEFAULT` 改为 `"enabled"`。

用户侧也可以在数据目录的 `settings.json` 写 `"online_adapter": "disabled"` 自行关闭；用户设置不能在发布默认关闭时打开在线功能。

