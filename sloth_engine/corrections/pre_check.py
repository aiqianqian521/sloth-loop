"""Loop 前置检查脚本 —— 在执行 loop 前校验矫正规则是否就绪。

v2.1 移植-P0: 引入 HookOutput 标准化输出，每项检查结果可叠加合并。

用法:
    python corrections/pre_check.py                  # 检查全部规则
    python corrections/pre_check.py --rule R4        # 只检查参数扫描规则
    python corrections/pre_check.py --work-dir xxx   # 指定 work_ooda 目录检查 OODA 完整性
"""

import json
import os
import sys
from pathlib import Path

# 支持从 sloth_engine 根目录或 corrections/ 子目录运行
_ENGINE = Path(__file__).resolve().parent.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from hook_protocol import (HookOutput, GuardPort, InMemoryGuardPort,
                           merge_hook_outputs,
                           make_ask, make_block, make_warn, make_allow)

CORRECTIONS_DIR = Path(__file__).parent
PLAYBOOK_PATH = CORRECTIONS_DIR / "playbook.json"


def load_playbook():
    if not PLAYBOOK_PATH.exists():
        return None
    with open(PLAYBOOK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def check_ooda_completeness(work_ooda_dir=None):
    """R2+R6: 检查 OODA 流程完整性。"""
    if work_ooda_dir is None:
        # 找最近的 work_ooda 任务目录
        cwd = Path.cwd()
        ooda_root = cwd / "work_ooda"
        if not ooda_root.exists():
            return False, "work_ooda/ 目录不存在"
        task_dirs = sorted(
            [d for d in ooda_root.iterdir() if d.is_dir() and not d.name.startswith("_")],
            reverse=True,
        )
        if not task_dirs:
            return False, "work_ooda/ 下无任务目录"
        task_dir = task_dirs[0]
    else:
        task_dir = Path(work_ooda_dir)

    required = ["00-purpose.md", "state.md"]
    missing = [f for f in required if not (task_dir / f).exists()]

    # 检查是否有逐轮文件
    round_files = sorted(task_dir.glob("*-round-*.md"))
    if not round_files:
        missing.append("round-N.md (至少1个)")

    # 检查 state.md 是否有 [post-hoc] 标记
    state_path = task_dir / "state.md"
    posthoc = False
    if state_path.exists():
        content = state_path.read_text(encoding="utf-8")
        if "[post-hoc]" in content:
            posthoc = True

    if missing:
        return False, f"缺少文件: {', '.join(missing)}"
    if posthoc:
        return False, "state.md 含 [post-hoc] 标记——记录是事后补的，可信度降级"

    return True, f"OODA 完整: {task_dir.name}"


def check_param_scan_plan(task_context=None):
    """R4: 检查是否有参数扫描计划。"""
    playbook = load_playbook()
    rule4 = next((r for r in playbook["rules"] if r["id"] == "R4"), None)
    if not rule4:
        return False, "playbook 中未找到 R4 规则"

    required = rule4["param_scan_required"]
    if task_context is None:
        return None, f"参数扫描要求: 最少 {required['min_values']} 个值, 需输出 {required['must_output']}"

    missing_outputs = [k for k in required["must_output"] if k not in task_context]
    if missing_outputs:
        return False, f"参数扫描计划不完整，缺少: {missing_outputs}"
    if task_context.get("values_tested", 0) < required["min_values"]:
        return False, f"参数值不足: {task_context['values_tested']} < {required['min_values']}"

    return True, "参数扫描计划完整"


def check_five_window(windows_tested=None, cross_window_std=None):
    """R5: 检查五窗口全量验证。"""
    playbook = load_playbook()
    rule5 = next((r for r in playbook["rules"] if r["id"] == "R5"), None)
    if not rule5:
        return False, "playbook 中未找到 R5 规则"

    required_windows = rule5["windows_required"]
    std_threshold = rule5["std_threshold"]

    if windows_tested is None and cross_window_std is None:
        return None, f"五窗口要求: {required_windows}, std < {std_threshold}pp"

    if windows_tested is not None:
        if windows_tested < rule5["min_windows"]:
            return False, f"窗口不足: {windows_tested} < {rule5['min_windows']} (需要 {required_windows})"
    if cross_window_std is not None:
        if cross_window_std >= std_threshold:
            return False, f"跨窗口 std={cross_window_std}pp >= {std_threshold}pp 硬门禁，结论不可信"

    return True, "五窗口验证通过"


def run_all_checks(work_dir=None, task_context=None):
    """执行全部规则检查，返回 (all_pass, results)"""
    playbook = load_playbook()
    if playbook is None:
        return False, [("playbook加载", False, "playbook.json 不存在")]

    results = []

    # R1: 规则文件存在性检查
    if PLAYBOOK_PATH.exists():
        results.append(("R1-学习记录已加载", True, "playbook.json 存在"))
    else:
        results.append(("R1-学习记录已加载", False, "playbook.json 缺失"))

    # R2+R6: OODA 完整性
    ooda_ok, ooda_msg = check_ooda_completeness(work_dir)
    results.append(("R2+R6-OODA流程完整", ooda_ok, ooda_msg))

    # R4: 参数扫描
    param_ok, param_msg = check_param_scan_plan(task_context)
    if param_ok is not None:
        results.append(("R4-参数扫描", param_ok, param_msg))
    else:
        results.append(("R4-参数扫描(待验证)", None, param_msg))

    # R5: 五窗口
    window_ok, window_msg = check_five_window()
    if window_ok is not None:
        results.append(("R5-五窗口全量", window_ok, window_msg))
    else:
        results.append(("R5-五窗口全量(待验证)", None, window_msg))

    return results


def _result_to_hook(row: tuple) -> HookOutput:
    """将 (rule_name, ok, msg) 元组转为 HookOutput。"""
    name, ok, msg = row
    rule_id = name.split("-")[0] if "-" in name else name
    if ok is True:
        return make_allow(f"{name}: {msg}", rule_id=rule_id)
    elif ok is False:
        return make_block(f"{name}: {msg}", rule_id=rule_id)
    else:
        # ok is None → requires a human decision; do not synchronously prompt.
        return make_ask(f"{name}: {msg}", rule_id=rule_id,
                        gate="pre_check", requires_input=True)


def run_all_hooks(work_dir=None, task_context=None,
                  guard: GuardPort | None = None) -> HookOutput:
    """执行全部规则检查，返回合并的 HookOutput。

    这是 v2.1 移植-P0 的新接口：与 hooks_check.py 的 run_all_checks()
    输出格式一致，可通过 merge_hook_outputs() 叠加。
    """
    results = run_all_checks(work_dir, task_context)
    outputs = [_result_to_hook(r) for r in results]
    merged = merge_hook_outputs(outputs)
    return guard.route(merged) if guard is not None else merged


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Loop 前置检查")
    parser.add_argument("--rule", help="只检查指定规则 (R1-R6)")
    parser.add_argument("--work-dir", help="work_ooda 任务目录路径")
    parser.add_argument("--param-values", type=int, help="已扫描参数值数量 (R4)")
    parser.add_argument("--windows", type=int, help="已验证窗口数 (R5)")
    parser.add_argument("--std", type=float, help="跨窗口 std (R5)")
    args = parser.parse_args()

    print("=" * 50)
    print("Loop 前置矫正检查")
    print(f"规则来源: {PLAYBOOK_PATH}")
    print("=" * 50)

    playbook = load_playbook()
    if playbook is None:
        print("[FAIL] playbook.json 不存在，无法检查")
        sys.exit(1)

    all_pass = True
    warnings = 0
    cli_outputs = []

    for rule in playbook["rules"]:
        rid = rule["id"]

        if args.rule and rid != args.rule:
            continue

        severity = rule["severity"].upper()
        tag = "[BLOCK]" if severity == "BLOCK" else "[WARN]"

        if rid == "R4" and args.param_values is not None:
            ok, msg = check_param_scan_plan({"values_tested": args.param_values})
            status = "PASS" if ok else "FAIL"
            print(f"  {tag} {rid} {status}: {msg}")
            cli_outputs.append(_result_to_hook((rid, ok, msg)))
            if not ok:
                all_pass = False
        elif rid == "R4":
            ok, msg = check_param_scan_plan(None)
            print(f"  {tag} {rid} ASK: {msg}")
            cli_outputs.append(_result_to_hook((rid, ok, msg)))
        elif rid == "R5" and (args.windows is not None or args.std is not None):
            ok, msg = check_five_window(args.windows, args.std)
            status = "PASS" if ok else "FAIL"
            print(f"  {tag} {rid} {status}: {msg}")
            cli_outputs.append(_result_to_hook((rid, ok, msg)))
            if not ok:
                all_pass = False
        elif rid == "R5":
            ok, msg = check_five_window()
            print(f"  {tag} {rid} ASK: {msg}")
            cli_outputs.append(_result_to_hook((rid, ok, msg)))
        elif rid in ("R2", "R6"):
            ok, msg = check_ooda_completeness(args.work_dir)
            status = "PASS" if ok else "FAIL"
            print(f"  {tag} {rid} {status}: {msg}")
            cli_outputs.append(_result_to_hook((rid, ok, msg)))
            if not ok and severity == "block":
                all_pass = False
            elif not ok:
                warnings += 1
        else:
            # 规则存在即可
            print(f"  {tag} {rid} OK: {rule['name']}")
            cli_outputs.append(make_allow(f"{rid}: rule exists", rule_id=rid))

    guard = InMemoryGuardPort()
    routed = guard.route(merge_hook_outputs(cli_outputs))
    print("-" * 50)
    if routed.requires_input():
        print("结论: 等待人工确认，不可直接开跑")
    elif routed.is_blocking() or not all_pass:
        print("结论: 有阻断项未通过，先修再跑")
    elif all_pass and warnings == 0:
        print("结论: 全部通过，可以开跑 → python orchestrator.py --once")
    elif all_pass:
        print(f"结论: {warnings} 条警告，建议处理后再跑")
    print("=" * 50)

    if routed.is_blocking():
        sys.exit(1)
    if routed.requires_input():
        print(f"[HOOK] ASK queued for human gate: {routed.reason}")
        sys.exit(2)


if __name__ == "__main__":
    main()
