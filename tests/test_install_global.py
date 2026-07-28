import importlib.util
import json
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
    / "install_global.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("install_global", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallGlobalTests(unittest.TestCase):
    def test_install_writes_owned_proxies_config_and_user_path(self):
        module = load_module()
        written_paths = []
        broadcasts = []

        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            module.install_global(
                codex_home=codex_home,
                real_codex="C:\\tools\\codex.cmd",
                python_executable="C:\\Python\\python.exe",
                read_path=lambda: "C:\\existing",
                write_path=written_paths.append,
                broadcast=lambda: broadcasts.append(True),
            )

            config = json.loads((codex_home / "resilient-codex-tasks" / "global.json").read_text())
            command_proxy = (codex_home / "bin" / "codex.cmd").read_text()
            powershell_proxy = (codex_home / "bin" / "codex.ps1").read_text()
            self.assertEqual(config["real_codex"], "C:\\tools\\codex.cmd")
            self.assertIn("global_proxy.py", command_proxy)
            self.assertIn("global_proxy.py", powershell_proxy)
            self.assertTrue(written_paths[0].startswith(str(codex_home / "bin")))
            self.assertEqual(broadcasts, [True])

    def test_path_update_does_not_duplicate_an_expanded_environment_entry(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir) / "bin"
            with patch.dict(module.os.environ, {"RETRY_PROXY_BIN": str(bin_dir)}, clear=False):
                updated_path = module.prepend_path("%RETRY_PROXY_BIN%;C:\\existing", bin_dir)

        self.assertEqual(updated_path, f"{bin_dir};C:\\existing")

    def test_uninstall_removes_only_owned_files_and_path_entry(self):
        module = load_module()
        written_paths = []

        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            bin_dir = codex_home / "bin"
            module.install_global(
                codex_home=codex_home,
                real_codex="C:\\tools\\codex.cmd",
                python_executable="C:\\Python\\python.exe",
                read_path=lambda: "C:\\existing",
                write_path=lambda value: None,
                broadcast=lambda: None,
            )
            (bin_dir / "unrelated.cmd").write_text("keep", encoding="utf-8")

            module.uninstall_global(
                codex_home=codex_home,
                read_path=lambda: f"{bin_dir};C:\\existing",
                write_path=written_paths.append,
                broadcast=lambda: None,
            )

            self.assertFalse((bin_dir / "codex.cmd").exists())
            self.assertFalse((bin_dir / "codex.ps1").exists())
            self.assertTrue((bin_dir / "unrelated.cmd").exists())
            self.assertFalse((codex_home / "resilient-codex-tasks" / "global.json").exists())
            self.assertEqual(written_paths, ["C:\\existing"])

    def test_reinstall_keeps_the_saved_real_cli_path(self):
        module = load_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            config_path = codex_home / "resilient-codex-tasks" / "global.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"real_codex": "C:\\npm\\codex.cmd"}), encoding="utf-8")
            with patch.object(module.os, "name", "nt"), patch.object(
                module, "find_real_codex"
            ) as find_real_codex, patch.object(
                module, "install_global", return_value={"real_codex": "C:\\npm\\codex.cmd"}
            ) as install:
                exit_code = module.main(["install", "--codex-home", str(codex_home)])

        self.assertEqual(exit_code, 0)
        find_real_codex.assert_not_called()
        self.assertEqual(install.call_args.kwargs["real_codex"], "C:\\npm\\codex.cmd")


if __name__ == "__main__":
    unittest.main()
