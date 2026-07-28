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
    / "global_proxy.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("global_proxy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GlobalProxyTests(unittest.TestCase):
    def test_only_intercepts_new_exec_tasks(self):
        module = load_module()

        self.assertTrue(module.should_intercept(["exec", "finish the task"], {}))
        self.assertTrue(module.should_intercept(["exec", "finish the task"], {"CODEX_RETRY_BYPASS": "0"}))
        self.assertFalse(module.should_intercept(["exec", "resume", "thread-123"], {}))
        self.assertFalse(module.should_intercept(["exec", "--help"], {}))
        self.assertFalse(module.should_intercept(["mcp", "list"], {}))
        self.assertFalse(module.should_intercept(["exec", "finish the task"], {"CODEX_RETRY_BYPASS": "1"}))

    def test_injects_json_immediately_after_exec(self):
        module = load_module()

        self.assertEqual(
            module.ensure_json_output(["exec", "--full-auto", "finish the task"]),
            ["exec", "--json", "--full-auto", "finish the task"],
        )
        self.assertEqual(
            module.ensure_json_output(["exec", "--json", "finish the task"]),
            ["exec", "--json", "finish the task"],
        )

    def test_environment_overrides_retry_configuration(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "global.json"
            config_path.write_text(json.dumps({"real_codex": "C:\\tools\\codex.cmd"}), encoding="utf-8")
            with patch.dict(
                module.os.environ,
                {
                    "CODEX_RETRY_DELAYS": "1,2",
                    "CODEX_RETRY_CLIENT_DELAYS": "3",
                    "CODEX_RETRY_LANGUAGE": "zh-CN",
                },
                clear=False,
            ):
                config = module.load_config(config_path)

        self.assertEqual(config["delays"], "1,2")
        self.assertEqual(config["client_delays"], "3")
        self.assertEqual(config["language"], "zh-CN")

    def test_runs_new_exec_tasks_through_retry_wrapper_with_unique_state(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = {
                "real_codex": "C:\\tools\\codex.cmd",
                "state_dir": str(root / "states"),
                "delays": "15,30",
                "client_delays": "5,20",
                "language": "zh-CN",
            }
            with patch.object(module, "load_config", return_value=config), patch.object(
                module.codex_retry, "main", return_value=0
            ) as retry:
                exit_code = module.run_cli(["exec", "finish the task"], root, {})

            self.assertEqual(exit_code, 0)
            retry_args = retry.call_args.args[0]
            command = json.loads(retry_args[retry_args.index("--command-json") + 1])
            state_file = Path(retry_args[retry_args.index("--state-file") + 1])
            self.assertEqual(command, ["C:\\tools\\codex.cmd", "exec", "--json", "finish the task"])
            self.assertEqual(state_file.parent, root / "states")
            self.assertEqual(retry_args[retry_args.index("--client-delays") + 1], "5,20")

    def test_passes_unmanaged_commands_to_the_real_cli(self):
        module = load_module()
        config = {"real_codex": "C:\\tools\\codex.cmd"}
        completed = subprocess.CompletedProcess(args=[], returncode=7)

        with patch.object(module, "load_config", return_value=config), patch.object(
            module.subprocess, "run", return_value=completed
        ) as run:
            exit_code = module.run_cli(["mcp", "list"], Path.cwd(), {})

        self.assertEqual(exit_code, 7)
        self.assertEqual(run.call_args.args[0], ["C:\\tools\\codex.cmd", "mcp", "list"])


if __name__ == "__main__":
    unittest.main()
