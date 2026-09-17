# src/where_my_job/rules/limits.py
"""规则资源限制。数值是产品上限，不是性能承诺。调用方在调用时读取属性（便于测试 monkeypatch）。"""
MAX_DEPTH = 8
MAX_PATTERN_LEN = 256
MAX_INPUT_TEXT = 20_000          # 单字段参与正则的最大字符数
MAX_RULES_TOTAL = 500            # classify + exclude + score.*.rules + global 合计
MAX_CONFIG_BYTES = 256 * 1024    # 按 UTF-8 字节计
EVAL_TIMEOUT_SEC = 20.0          # 整批求值超时（spawn 进程墙钟）
