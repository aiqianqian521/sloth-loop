#!/usr/bin/env bash
# Loop 自进化编排系统 - 生产定时触发包装 (循环驱动: Cron 维度)
# 用法: 加入 crontab → 每5分钟触发一轮回测循环
#   */5 * * * * /path/to/sloth_engine/cron_wrapper.sh >> /var/log/loop.log 2>&1

set -euo pipefail

PROJECT_ROOT="<SLOTH_ROOT>"
LOG_DIR="$PROJECT_ROOT/sloth_engine/data/logs"
mkdir -p "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/loop_$TS.log"

cd "$PROJECT_ROOT"

# 1. 环境检查
if [ ! -f "$PROJECT_ROOT/sloth_engine/orchestrator.py" ]; then
  echo "[cron] orchestrator.py 缺失，退出" >> "$LOG"
  exit 1
fi

# 2. 运行一轮（--once 调试用；生产可去掉改为持续）
python "$PROJECT_ROOT/sloth_engine/orchestrator.py" \
  --config "$PROJECT_ROOT/sloth_engine/config.yaml" \
  --signals "$PROJECT_ROOT/sloth_engine/data/signals_seed.json" \
  >> "$LOG" 2>&1

# 3. 异常告警（扩展点: 接入邮件/钉钉/企业微信）
if [ $? -ne 0 ]; then
  echo "[cron] 回测循环异常，请检查 $LOG" >> "$LOG"
fi

# 4. 日志轮转（保留30天）
find "$LOG_DIR" -name "loop_*.log" -mtime +30 -delete
