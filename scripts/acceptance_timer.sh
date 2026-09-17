#!/usr/bin/env bash
# scripts/acceptance_timer.sh — 给验收步骤计时：bash scripts/acceptance_timer.sh <命令...>
set -uo pipefail
start=$(date +%s)
"$@"
rc=$?
end=$(date +%s)
echo "elapsed_seconds=$((end - start)) exit_code=$rc cmd=$*"
exit $rc
