#!/usr/bin/env python3
"""Install, inspect, or remove the Windows global Codex retry proxy."""

import argparse
import ctypes
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, Optional


PROXY_MARKER = "resilient-codex-tasks global proxy"
CONFIG_DIRECTORY_NAME = "resilient-codex-tasks"


def owned_proxy_content(python_executable: str, proxy_script: Path) -> Dict[str, str]:
    escaped_python = python_executable.replace("'", "''")
    escaped_proxy_script = str(proxy_script).replace("'", "''")
    command_proxy = "\n".join(
        (
            "@echo off",
            f"rem {PROXY_MARKER}",
            f'"{python_executable}" "{proxy_script}" %*',
            "exit /b %ERRORLEVEL%",
            "",
        )
    )
    powershell_proxy = "\n".join(
        (
            f"# {PROXY_MARKER}",
            f"& '{escaped_python}' '{escaped_proxy_script}' @args",
            "exit $LASTEXITCODE",
            "",
        )
    )
    return {"codex.cmd": command_proxy, "codex.ps1": powershell_proxy}


def path_entries(path_value: str):
    return [entry for entry in path_value.split(";") if entry]


def same_path(left: str, right: str) -> bool:
    normalized_left = os.path.normcase(os.path.normpath(os.path.expandvars(left)))
    normalized_right = os.path.normcase(os.path.normpath(os.path.expandvars(right)))
    return normalized_left == normalized_right


def prepend_path(path_value: str, entry: Path) -> str:
    entry_text = str(entry)
    remaining = [value for value in path_entries(path_value) if not same_path(value, entry_text)]
    return ";".join([entry_text, *remaining])


def remove_path_entry(path_value: str, entry: Path) -> str:
    return ";".join(value for value in path_entries(path_value) if not same_path(value, str(entry)))


def read_user_path() -> str:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, "Path")[0])
    except FileNotFoundError:
        return ""


def write_user_path(path_value: str) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, path_value)


def broadcast_environment_change() -> None:
    if os.name != "nt":
        return
    result = ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0, 5000, None)
    if not result:
        raise OSError("Unable to broadcast the user environment update")


def is_owned_proxy(path: Path) -> bool:
    try:
        return PROXY_MARKER in path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False


def write_proxy(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(content)


def install_global(
    *,
    codex_home: Path,
    real_codex: str,
    python_executable: str,
    read_path: Callable[[], str] = read_user_path,
    write_path: Callable[[str], None] = write_user_path,
    broadcast: Callable[[], None] = broadcast_environment_change,
) -> Dict[str, str]:
    bin_dir = codex_home / "bin"
    config_dir = codex_home / CONFIG_DIRECTORY_NAME
    proxy_script = Path(__file__).resolve().with_name("global_proxy.py")
    for proxy_name in ("codex.cmd", "codex.ps1"):
        proxy_path = bin_dir / proxy_name
        if proxy_path.exists() and not is_owned_proxy(proxy_path):
            raise ValueError(f"Refusing to overwrite unmanaged proxy: {proxy_path}")

    bin_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    for proxy_name, content in owned_proxy_content(python_executable, proxy_script).items():
        write_proxy(bin_dir / proxy_name, content)

    config = {
        "schema_version": 1,
        "real_codex": real_codex,
        "state_dir": str(config_dir / "states"),
        "delays": "15,30,60,120,240,300",
        "client_delays": "5,20",
        "language": "en",
    }
    (config_dir / "global.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    previous_path = read_path()
    updated_path = prepend_path(previous_path, bin_dir)
    if updated_path != previous_path:
        write_path(updated_path)
        broadcast()
    return config


def uninstall_global(
    *,
    codex_home: Path,
    read_path: Callable[[], str] = read_user_path,
    write_path: Callable[[str], None] = write_user_path,
    broadcast: Callable[[], None] = broadcast_environment_change,
) -> None:
    bin_dir = codex_home / "bin"
    for proxy_name in ("codex.cmd", "codex.ps1"):
        proxy_path = bin_dir / proxy_name
        if proxy_path.exists():
            if not is_owned_proxy(proxy_path):
                raise ValueError(f"Refusing to remove unmanaged proxy: {proxy_path}")
            proxy_path.unlink()

    config_path = codex_home / CONFIG_DIRECTORY_NAME / "global.json"
    try:
        config_path.unlink()
    except FileNotFoundError:
        pass

    previous_path = read_path()
    updated_path = remove_path_entry(previous_path, bin_dir)
    if updated_path != previous_path:
        write_path(updated_path)
        broadcast()


def find_real_codex(codex_home: Path) -> str:
    proxy_dir = (codex_home / "bin").resolve()
    for name in ("codex.cmd", "codex.exe", "codex"):
        candidate = shutil.which(name)
        if candidate and proxy_dir not in Path(candidate).resolve().parents:
            return str(Path(candidate).resolve())
    raise ValueError("Unable to find the real Codex CLI. Pass --real-codex with its full path.")


def saved_real_codex(codex_home: Path) -> Optional[str]:
    config_path = codex_home / CONFIG_DIRECTORY_NAME / "global.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    real_codex = config.get("real_codex") if isinstance(config, dict) else None
    return real_codex if isinstance(real_codex, str) and real_codex else None


def installation_status(codex_home: Path) -> Dict[str, object]:
    bin_dir = codex_home / "bin"
    config_path = codex_home / CONFIG_DIRECTORY_NAME / "global.json"
    return {
        "config_path": str(config_path),
        "configured": config_path.is_file(),
        "command_proxy": is_owned_proxy(bin_dir / "codex.cmd"),
        "powershell_proxy": is_owned_proxy(bin_dir / "codex.ps1"),
        "path_precedence": any(same_path(entry, str(bin_dir)) for entry in path_entries(os.environ.get("Path", ""))),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "status"))
    parser.add_argument("--real-codex", help="Full path to the real Codex CLI")
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if os.name != "nt":
        print("Global proxy installation is currently supported on Windows only.", file=sys.stderr)
        return 64
    try:
        if args.action == "install":
            real_codex = args.real_codex or saved_real_codex(args.codex_home) or find_real_codex(args.codex_home)
            config = install_global(
                codex_home=args.codex_home,
                real_codex=real_codex,
                python_executable=sys.executable,
            )
            print(f"Installed global Codex retry proxy. Real CLI: {config['real_codex']}")
        elif args.action == "uninstall":
            uninstall_global(codex_home=args.codex_home)
            print("Removed global Codex retry proxy.")
        else:
            print(json.dumps(installation_status(args.codex_home), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        print(f"Global Codex retry installation error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
