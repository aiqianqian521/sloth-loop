#!/usr/bin/env python
"""
演示回测脚本 (Mock Backtest) —— 用来跑通 loop，不是真实回测。

作用:
  1. 让你在还没接入 lh 真实回测代码时，就能把整条自进化链路跑起来看效果
  2. 作为「回测脚本 I/O 契约」的活文档 —— 换成真实脚本时照着这个接口改

契约 (sloth_engine/adapters/backtest_adapter.py 依赖):
  输入:  --input <path>   一个 JSON 文件
         {"signals":[{"signal_pattern":..,"market_condition":..}, ...],
          "params":{...},
          "success_starting_points":[...]}
  输出:  --output <path>  写一个 JSON 文件
         {"trades":[{"signal_pattern":..,"market_condition":..,"pnl":float,
                     "failure_reason":str, "entry_condition":..,"stop_loss":..,
                     "take_profit":..,"position_size":..}, ...],
          "pnl":{"total":float}, "win_rate":"55%", "sharpe":1.2}
  退出码: 0 = 成功, 非0 = 失败(stderr 会被编排器记进失败库)
扩展参数: --max-bars <int>  与真实回测契约对齐(接受但 mock 不读K线, 仅 no-op)

确定性:
  同样的 signal_pattern + market_condition + seed → 同样的结果。
  这样回归测试可复现。用 --seed 改变结果分布。

强制失败 (用于演练"回测崩了怎么办"):
  --fail-mode crash    直接非零退出
  --fail-mode empty    正常退出但不写输出文件
  --fail-mode timeout  睡到超时
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

# 演示用的失败原因池 —— 措辞刻意对齐 orchestrator._classify_failure 的关键词
FAILURE_REASONS = [
    "极端位置追单，入场时已在区间顶部",
    "绝对位置盲区，未识别关键阻力",
    "先触止损后价格达标",
    "连续同方向偏移，信号方向判断失效",
    "震荡区间假突破",
    "证据不足即入场",
]


def _rand01(*parts: str) -> float:
    """用 hash 造确定性伪随机数 [0,1)。"""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def simulate(signals: list[dict], seed: str, win_bias: float) -> dict:
    trades = []
    for s in signals:
        sp = str(s.get("signal_pattern", "unknown"))
        mc = str(s.get("market_condition", "unknown"))
        # OODA R6: 不能把列表下标混进 hash。
        # 否则「排除掉一条信号」会让其余信号的回测结果全变 —— 真实回测没有这种耦合，
        # 会让排除规则的效果无法归因。只用 (seed, 信号, 市场) 决定结果。
        r = _rand01(seed, sp, mc)
        # win_bias 越高越容易盈利；已知坏模式(含"极端"/"盲区")强制偏亏
        bad = ("极端" in sp) or ("盲区" in sp) or ("追单" in sp)
        win = (r < win_bias) and not bad
        magnitude = round(0.5 + r * 4.5, 2)
        t = {
            "signal_pattern": sp,
            "market_condition": mc,
            "pnl": magnitude if win else -magnitude,
        }
        if win:
            t.update({
                "entry_condition": f"{sp} 确认后回踩不破",
                "stop_loss": "1.5%",
                "take_profit": f"{magnitude * 2:.1f}%",
                "position_size": "20%",
            })
        else:
            idx = int(_rand01(seed, "reason", sp, mc) * len(FAILURE_REASONS))
            t["failure_reason"] = FAILURE_REASONS[idx % len(FAILURE_REASONS)]
        trades.append(t)

    total = round(sum(t["pnl"] for t in trades), 2)
    wins = len([t for t in trades if t["pnl"] > 0])
    wr = f"{(wins / len(trades) * 100):.0f}%" if trades else "0%"
    return {
        "trades": trades,
        "pnl": {"total": total},
        "win_rate": wr,
        "sharpe": round(total / (len(trades) or 1) / 2, 2),
        "_note": "MOCK 数据，非真实回测结果",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", default="demo")
    ap.add_argument("--win-bias", type=float, default=0.45,
                    help="盈利概率基准，0~1，越大越容易赚")
    ap.add_argument("--max-bars", type=int, default=None,
                    help="与真实回测契约对齐(接受但 mock 不读K线, 仅 no-op)")
    ap.add_argument("--fail-mode", default="", choices=["", "crash", "empty", "timeout"])
    args = ap.parse_args()

    if args.fail_mode == "crash":
        print("MOCK: 模拟回测脚本崩溃", file=sys.stderr)
        return 3
    if args.fail_mode == "timeout":
        time.sleep(99999)

    inp = json.loads(Path(args.input).read_text(encoding="utf-8"))
    signals = inp.get("signals", [])
    result = simulate(signals, args.seed, args.win_bias)

    if args.fail_mode == "empty":
        print("MOCK: 故意不写输出文件")
        return 0

    outp = Path(args.output)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MOCK: {len(signals)} 个信号 -> {len(result['trades'])} 笔交易, "
          f"总盈亏 {result['pnl']['total']}%, 胜率 {result['win_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
