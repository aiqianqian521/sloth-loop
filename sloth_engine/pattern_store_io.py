"""PatternStore JSON 互通 mixin — H1-P1 godfile 拆分首切（行为保持）。

export_json/import_json 原为 memory_store.PatternStore 方法，移至本 mixin；
PatternStore(BasePatternStore, PatternStoreIO) 继承后公共 API 不变。
JSON 互通零 yaml 依赖（YAML 互通留后续 slice：涉共享 _require_yaml/_extract_yaml_docs）。
拆分目标：缓解 memory_store godfile(scheme high①>800行)；本切 ~57 行，后续 slice 继续。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path



# OODA R1: yaml 改为「按需导入」。原来顶层 import 导致未装 PyYAML 的机器
# 连 `--once` 都跑不起来。YAML 只在知识库互通时才需要。
try:
    import yaml  # type: ignore
    HAS_YAML = True
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore
    HAS_YAML = False

def _require_yaml():
    if not HAS_YAML:
        raise RuntimeError(
            "此功能需要 PyYAML：pip install PyYAML\n"
            "（仅知识库 Markdown 互通需要，核心 loop 不依赖）"
        )
import re

class PatternStoreIO:
    """JSON 互通（OODA R10：零依赖，可进 git，可跨机器）。由 PatternStore 继承。"""

    def export_json(self, path: str | Path) -> dict:
        """把整个模式库导出成一个可读 JSON。
        SQLite 是二进制，进不了 git diff、换机器也不好带；JSON 两个问题都解决。
        """
        payload = {
            "exported_at": datetime.now().isoformat(),
            "failure_patterns": self.load_failure_patterns(),
            "success_patterns": self.load_success_patterns(),
            "rounds": self.get_rounds(),
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"failures": len(payload["failure_patterns"]),
                "successes": len(payload["success_patterns"]),
                "rounds": len(payload["rounds"]), "path": str(p)}

    def import_json(self, path: str | Path) -> dict:
        """从导出的 JSON 恢复。同 id 覆盖，不同 id 追加。"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"导入文件不存在: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        fs = data.get("failure_patterns", []) or []
        ss = data.get("success_patterns", []) or []
        # 扁平行 → append_* 期望的嵌套结构
        self.append_failure([{
            **f,
            "impact": {"trades": f.get("impact_trades", 0),
                       "win_rate": f.get("impact_win_rate"),
                       "total_pnl": f.get("impact_total_pnl")},
        } for f in fs if f.get("id")])
        self.append_success([{
            **s,
            "parameters": {"entry": s.get("entry"), "stop_loss": s.get("stop_loss"),
                           "take_profit": s.get("take_profit"),
                           "position_size": s.get("position_size")},
            "performance": {"quarters_tested": s.get("quarters_tested", 0),
                            "quarters_positive": s.get("quarters_positive", 0),
                            "avg_sharpe": s.get("avg_sharpe", 0),
                            "avg_annual_excess": s.get("avg_annual_excess")},
        } for s in ss if s.get("id")])
        # append_* 不写 occurrences/last_seen（靠列默认值），这里补回，保证往返不丢计数
        with self._connect() as conn:
            for f in fs:
                if not f.get("id"):
                    continue
                conn.execute(
                    "UPDATE failure_patterns SET occurrences=?, last_seen=? WHERE id=?",
                    (f.get("occurrences", 1), f.get("last_seen"), f["id"]))
            for s in ss:
                if not s.get("id"):
                    continue
                conn.execute(
                    "UPDATE success_patterns SET occurrences=?, last_seen=? WHERE id=?",
                    (s.get("occurrences", 1), s.get("last_seen"), s["id"]))
        return {"failures": len(fs), "successes": len(ss)}

    def export_to_yaml(self, kb_failure_md: str | Path, kb_success_md: str | Path):
        """把 SQLite 内容导出回知识库 Markdown（覆盖 YAML 代码块）。"""
        _require_yaml()
        # MVP 简化: 直接写 YAML 文件。知识库的 .md 包装由 Agent 维护。
        fs = self.load_failure_patterns()
        ss = self.load_success_patterns()
        Path(kb_failure_md).write_text(
            yaml.safe_dump(fs, allow_unicode=True, sort_keys=False), encoding="utf-8")
        Path(kb_success_md).write_text(
            yaml.safe_dump(ss, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def import_from_yaml(self, kb_failure_md: str | Path, kb_success_md: str | Path):
        """从知识库导入（首次初始化或人工修正后同步）。

        兼容两种来源:
          - 纯 .yaml 文件 → 直接 safe_load
          - 知识库 .md 文件 → 提取所有 ```yaml 代码块并合并
        每条记录是 list[dict]，多个代码块的结果拼接。
        """
        _require_yaml()
        fp = Path(kb_failure_md)
        sp = Path(kb_success_md)
        if fp.exists():
            data = self._extract_yaml_docs(fp.read_text(encoding="utf-8"))
            if data:
                self.append_failure(data)
        if sp.exists():
            data = self._extract_yaml_docs(sp.read_text(encoding="utf-8"))
            if data:
                self.append_success(data)

    @staticmethod
    def _extract_yaml_docs(text: str) -> list[dict]:
        """从文本中提取所有 YAML 文档。支持纯 YAML 或多段 ```yaml 代码块。"""
        _require_yaml()
        # 优先提取 fenced yaml 代码块
        blocks = re.findall(r"```yaml\s*(.*?)```", text, re.DOTALL)
        if not blocks:
            # 退回: 尝试整段作为单个 YAML 文档
            try:
                d = yaml.safe_load(text)
                return d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
            except yaml.YAMLError:
                return []
        result: list[dict] = []
        for b in blocks:
            try:
                d = yaml.safe_load(b)
            except yaml.YAMLError:
                continue
            if isinstance(d, list):
                result.extend(d)
            elif isinstance(d, dict):
                result.append(d)
        # 过滤掉示例块（含 "F-YYYYMMDD-NNN" 占位 id 的）
        result = [r for r in result if isinstance(r, dict) and r.get("id")
                  and "YYYYMMDD" not in str(r.get("id"))]
        return result
