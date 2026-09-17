# 私有回归

私有回归通过环境变量 `WMJ_PRIVATE_MANIFEST` 指向一份 import_manifest JSON，例如指向
`~/Desktop/boss-hunter-handoff/data-scripts` 的 42 个 `<城市>_<关键词>.json`。manifest 与原始文件都不进仓库。

本机一次性生成：

```bash
uv run python - <<'PY'
import json, glob, os, re, hashlib
d = os.path.expanduser("~/Desktop/boss-hunter-handoff/data-scripts")
files = sorted(f for f in glob.glob(os.path.join(d, "*_*.json")) if re.match(r"^[一-鿿]+_", os.path.basename(f)))
assert len(files) == 42, len(files)
man = {"schema_version": 1, "timezone_assumption": "Asia/Shanghai",
       "files": [{"path": f, "sha256": hashlib.sha256(open(f, "rb").read()).hexdigest()} for f in files]}
out = os.path.expanduser("~/.where-my-job-private/manifest-20260914.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(man, open(out, "w"), ensure_ascii=False, indent=1)
print(out)
PY
```

运行：`WMJ_PRIVATE_MANIFEST=~/.where-my-job-private/manifest-20260914.json uv run pytest tests/regression -q`。未设置时整组 skip；设置后缺文件或哈希不符必须失败，不得静默跳过。

## 私有回归的 scoring 配置
不需要手写或放置私有 scoring 文件。`tests/regression/scoring_presets.py::frozen_scoring` 在 pytest 临时目录里按带 sha256 的 manifest 生成 `legacy-20260914` 与 `handoff-intent-v1` 两份冻结配置，先经 `validate_object("scoring", ...)` 校验，再通过真实 CLI 运行 `match`。生成结果不写入本目录，也不进入 git。
