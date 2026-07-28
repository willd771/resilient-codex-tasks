import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "resilient-codex-tasks"
    / "scripts"
    / "codex_retry.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("codex_retry", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CodexRetryTests(unittest.TestCase):
    def test_classifies_transient_statuses_as_retryable(self):
        module = load_module()

        for status in (429, 502, 503):
            result = module.classify_failure(f"HTTP {status} temporary failure")
            self.assertEqual(result.kind, module.FailureKind.TRANSIENT)

    def test_only_quota_related_403_is_terminal_quota(self):
        module = load_module()

        quota = module.classify_failure("HTTP 403: insufficient_quota; balance exhausted")
        forbidden = module.classify_failure("HTTP 403: forbidden by workspace policy")

        self.assertEqual(quota.kind, module.FailureKind.QUOTA_EXHAUSTED)
        self.assertEqual(forbidden.kind, module.FailureKind.NON_RETRYABLE)

    def test_extracts_thread_id_from_jsonl_output(self):
        module = load_module()

        thread_id = module.extract_thread_id(
            '{"type":"thread.started","thread_id":"thread-123"}\n'
        )

        self.assertEqual(thread_id, "thread-123")

    def test_retries_transient_failure_by_resuming_the_same_thread(self):
        module = load_module()
        first = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='{"type":"thread.started","thread_id":"thread-123"}\n',
            stderr="HTTP 503 service unavailable",
        )
        second = subprocess.CompletedProcess(args=[], returncode=0, stdout="completed\n", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "retry-state.json"
            with patch.object(module.subprocess, "run", side_effect=[first, second]) as run, patch.object(
                module.time, "sleep"
            ):
                exit_code = module.main(
                    [
                        "--prompt",
                        "finish the task",
                        "--cwd",
                        temp_dir,
                        "--state-file",
                        str(state_file),
                        "--delays",
                        "0",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(run.call_count, 2)
            initial_command = run.call_args_list[0].args[0]
            resumed_command = run.call_args_list[1].args[0]
            self.assertEqual(initial_command[1:3], ["exec", "--json"])
            self.assertIn("finish the task", initial_command)
            self.assertEqual(resumed_command[1:4], ["exec", "resume", "thread-123"])
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["thread_id"], "thread-123")

    def test_stops_without_retry_when_403_reports_insufficient_quota(self):
        module = load_module()
        quota_failure = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="HTTP 403 insufficient_quota"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "retry-state.json"
            with patch.object(module.subprocess, "run", return_value=quota_failure) as run, patch.object(
                module.time, "sleep"
            ):
                exit_code = module.main(
                    [
                        "--prompt",
                        "finish the task",
                        "--cwd",
                        temp_dir,
                        "--state-file",
                        str(state_file),
                        "--delays",
                        "0,0,0",
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertEqual(run.call_count, 1)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "quota_exhausted")

    def test_resumes_a_persisted_thread_after_the_wrapper_restarts(self):
        module = load_module()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="completed\n", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "retry-state.json"
            state_file.write_text(
                json.dumps(
                    {
                        "status": "retrying",
                        "prompt": "finish the task",
                        "thread_id": "thread-456",
                        "attempt": 2,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(module.subprocess, "run", return_value=completed) as run:
                exit_code = module.main(
                    [
                        "--resume",
                        str(state_file),
                        "--cwd",
                        temp_dir,
                        "--delays",
                        "0",
                    ]
                )

            self.assertEqual(exit_code, 0)
            resumed_command = run.call_args.args[0]
            self.assertEqual(resumed_command[1:4], ["exec", "resume", "thread-456"])

    def test_preserves_retry_budget_after_the_wrapper_restarts(self):
        module = load_module()
        transient_failure = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="HTTP 503 service unavailable"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "retry-state.json"
            state_file.write_text(
                json.dumps(
                    {
                        "status": "retrying",
                        "prompt": "finish the task",
                        "thread_id": "thread-789",
                        "attempt": 2,
                        "retry_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(module.subprocess, "run", return_value=transient_failure) as run, patch.object(
                module.time, "sleep"
            ) as sleep:
                exit_code = module.main(
                    [
                        "--resume",
                        str(state_file),
                        "--cwd",
                        temp_dir,
                        "--delays",
                        "0",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(run.call_count, 1)
            sleep.assert_not_called()
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "retry_exhausted")


if __name__ == "__main__":
    unittest.main()
