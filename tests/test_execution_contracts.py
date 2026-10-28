"""Dependency-free contract checks for registry and agent_prompt adapters."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from adapters.task_runner import TaskInput, TaskResult  # noqa: E402
from orchestrator import OODASteps  # noqa: E402
from tool_registry import ToolRegistry  # noqa: E402


class _Store:
    def __init__(self):
        self.failures = []
        self.successes = []

    def load_success_patterns(self):
        return []

    def find_failure_by_signature(self, *_):
        return None

    def find_failure(self, *_):
        return None

    def find_success(self, *_):
        return None

    def next_id(self, prefix):
        return f"{prefix}-{len(self.failures) + len(self.successes) + 1}"

    def append_failure(self, rows):
        self.failures.extend(rows)

    def append_success(self, rows):
        self.successes.extend(rows)

    def bump_failure(self, *_args, **_kwargs):
        raise AssertionError("unexpected existing failure")

    def bump_success(self, *_args, **_kwargs):
        raise AssertionError("unexpected existing success")

    def bump_fix_confidence(self, *_args, **_kwargs):
        raise AssertionError("unexpected confidence bump")


def main() -> None:
    original_act = OODASteps._act
    OODASteps._act = staticmethod(lambda *_args, **_kwargs: {
        "status": "error", "error": "retry boom", "task_result": None})
    try:
        skipped, attempts = OODASteps._act_with_retry(
            {"action": "execute"}, [{"signal_pattern": "retry"}], {}, _Store())
    finally:
        OODASteps._act = staticmethod(original_act)
    assert skipped["status"] == "skipped"
    assert skipped["execution_failed"] is True
    assert skipped["error"] == "retry boom"
    assert [attempt["strategy"] for attempt in attempts] == [
        "standard", "longer_timeout", "graceful_skip"]

    registry = ToolRegistry()
    registry.register_script("plain", lambda *_: {"status": "completed", "metrics": {"count": 1}})
    completed = registry.dispatch("plain", TaskInput(task_type="plain"))
    assert completed["execution"]["status"] == "succeeded"
    assert completed["output"]["status"] == "not_verified"
    assert completed["business"]["status"] == "not_evaluated"
    assert completed["provenance"]["adapter"] == "script"

    registry.register_agent("broken", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    failed = registry.dispatch("broken", TaskInput(task_type="broken"))
    assert failed["status"] == "error"
    assert failed["execution"]["code"] == "handler_exception"
    assert failed["errors"][0]["signature"] == "agent_prompt:handler_exception"

    blocked_registry = ToolRegistry()
    blocked_seen = []
    blocked_registry.register_script("blocked", lambda *_: {"status": "completed"})
    blocked_registry.add_pre_hook(lambda *_: None)
    blocked_registry.add_post_hook(lambda _name, result: blocked_seen.append(result["status"]))
    blocked = blocked_registry.dispatch("blocked", TaskInput(task_type="blocked-case"))
    assert blocked["status"] == "skipped"
    assert blocked["execution"]["code"] == "pre_hook_blocked"
    assert blocked["provenance"]["task_type"] == "blocked-case"
    assert blocked_seen == ["skipped"]

    post_failed_registry = ToolRegistry()
    post_failed_registry.register_script("post-fail", lambda *_: {"status": "completed"})
    post_failed_registry.add_post_hook(
        lambda *_: (_ for _ in ()).throw(RuntimeError("post boom")))
    post_failed = post_failed_registry.dispatch(
        "post-fail", TaskInput(task_type="post-fail-case"))
    assert post_failed["status"] == "error"
    assert post_failed["execution"]["code"] == "post_hook_exception"
    assert post_failed["task_result"]["execution"] == post_failed["execution"]

    mutation_registry = ToolRegistry()
    mutation_registry.register_script("mutate", lambda *_: {"status": "completed"})
    mutation_registry.add_post_hook(
        lambda _name, result: result["provenance"].update({"hook": "seen"}))
    mutated = mutation_registry.dispatch("mutate", TaskInput(task_type="mutation-case"))
    assert mutated["provenance"]["hook"] == "seen"
    assert mutated["task_result"]["provenance"]["hook"] == "seen"

    # Registry failures must survive Act -> Learn as TaskResult objects.
    learning_store = _Store()
    registry_result = OODASteps._act(
        {"action": "execute"}, [{"signal_pattern": "registry"}], {}, learning_store,
        {"name": "registry-case", "execution": {"type": "broken"}}, registry=registry,
    )
    learned = OODASteps._learn(
        registry_result, {"pass_count": 0, "fail_count": 1}, learning_store)
    assert isinstance(registry_result["task_result"], TaskResult)
    assert learned["new_failures"] >= 1

    with tempfile.TemporaryDirectory(prefix="loop-agent-contract-") as td:
        module = Path(td) / "contract_agent.py"
        (Path(td) / "broken_import_agent.py").write_text(
            "raise RuntimeError('module boom')\n", encoding="utf-8")
        module.write_text(
            "from adapters.task_runner import TaskRunner\n"
            "class ContractAgent(TaskRunner):\n"
            "    def __init__(self, settings=None):\n"
            "        self.settings = settings or {}\n"
            "    def run(self, input):\n"
            "        return {'status':'completed','metrics':{'score':1},'result':'ok'}\n"
            "    def validate_output(self, result):\n"
            "        return result.execution.get('status') == 'succeeded'\n"
            "class InitFailAgent(TaskRunner):\n"
            "    def __init__(self, settings=None): raise RuntimeError('init boom')\n"
            "    def run(self, input): return {}\n"
            "class RunFailAgent(TaskRunner):\n"
            "    def __init__(self, settings=None): pass\n"
            "    def run(self, input): raise RuntimeError('run boom')\n"
            "class ValidateFailAgent(TaskRunner):\n"
            "    def __init__(self, settings=None): pass\n"
            "    def run(self, input): return {'status':'completed'}\n"
            "    def validate_output(self, result): raise RuntimeError('validate boom')\n"
            "class PositiveAgent(TaskRunner):\n"
            "    def __init__(self, settings=None): pass\n"
            "    def run(self, input):\n"
            "        return {'status':'completed','metrics':{'sharpe':1.2},'trades':[{'signal_pattern':'gain','market_condition':'trend','pnl':2.0}]}\n"
            "    def validate_output(self, result): return True\n"
            "class DeclaredErrorAgent(TaskRunner):\n"
            "    def __init__(self, settings=None): pass\n"
            "    def run(self, input): return {'status':'error','error':'declared'}\n",
            encoding="utf-8",
        )
        sys.path.insert(0, td)
        try:
            result = OODASteps._act(
                {"action": "execute"}, [{"signal_pattern": "agent"}], {}, _Store(),
                {"name": "agent-case", "execution": {
                    "type": "agent_prompt", "entry": "contract_agent.ContractAgent"}},
            )
        finally:
            sys.path.remove(td)
            sys.modules.pop("contract_agent", None)
        contract = result["task_result"]
        assert isinstance(contract, TaskResult)
        assert contract.execution["status"] == "succeeded"
        assert contract.output["status"] == "not_verified"
        assert contract.business["status"] == "not_evaluated"
        assert contract.provenance["adapter"] == "agent_prompt"
        assert contract.provenance["task_type"] == "agent-case"

        sys.path.insert(0, td)
        import_failed = OODASteps._act(
            {"action": "execute"}, [{"signal_pattern": "agent"}], {}, _Store(),
            {"name": "agent-import-failure", "execution": {
                "type": "agent_prompt", "entry": "broken_import_agent.Anything"}},
        )
        assert import_failed["status"] == "error"
        assert import_failed["task_result"].execution["code"] == "import_execution_exception"

        for class_name, expected_code in [
            ("InitFailAgent", "runner_init_exception"),
            ("RunFailAgent", "runner_exception"),
            ("ValidateFailAgent", "output_validation_exception"),
        ]:
            failed_result = OODASteps._act(
                {"action": "execute"}, [{"signal_pattern": "agent"}], {}, _Store(),
                {"name": "agent-failure", "execution": {
                    "type": "agent_prompt", "entry": f"contract_agent.{class_name}"}},
            )
            assert failed_result["status"] == "error"
            assert failed_result["task_result"].execution["code"] == expected_code, (
                class_name, failed_result["task_result"].execution)

        declared = OODASteps._act(
            {"action": "execute"}, [{"signal_pattern": "agent"}], {}, _Store(),
            {"name": "agent-declared-error", "execution": {
                "type": "agent_prompt", "entry": "contract_agent.DeclaredErrorAgent"}},
        )
        assert declared["status"] == "error"

        positive_store = _Store()
        positive = OODASteps._act(
            {"action": "execute"}, [{"signal_pattern": "gain"}], {}, positive_store,
            {"name": "agent-positive", "execution": {
                "type": "agent_prompt", "entry": "contract_agent.PositiveAgent"}},
        )
        positive_learn = OODASteps._learn(
            positive, {"pass_count": 1, "fail_count": 0}, positive_store)
        assert positive_learn["new_successes"] == 1
        assert positive_store.successes[0]["performance"]["avg_sharpe"] == 1.2
        sys.path.remove(td)
        sys.modules.pop("contract_agent", None)

    print("PASS registry/agent_prompt result contracts")


def test_contract():
    """Pytest entry (cycle-16 A): keep these assertions inside the gate.

    This file used to be a manual script (``python tests/<file>``): pytest
    collected zero tests from it, so its assertions were never enforced by
    ``run_gate.py``.  The body is unchanged -- this wrapper only makes the very
    same checks run under pytest.
    """
    main()


if __name__ == "__main__":
    main()
