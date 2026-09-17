# src/where_my_job/release.py
"""发布级常量。离线 beta 发布时保持 "disabled"；在线门槛通过后改为 "enabled"（同时更新 README 状态行）。"""
ONLINE_ADAPTER_DEFAULT = "disabled"
