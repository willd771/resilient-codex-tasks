#!/usr/bin/env python3
"""Proxy selected global Codex CLI calls through the retry wrapper."""

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codex_retry


CONFIG_ENVIRONMENT_VARIABLE = "CODEX_RETRY_CONFIG"
DEFAULT_DELAYS = "15,30,60,120,240,300"
DEFAULT_CLIENT_DELAYS = "5,20"


def default_config_path() -> Path:
    return Path.home() / ".codex" / "resilient-codex-tasks" / "global.json"


def load_config(path: Optional[Path] = None) -> Dict[str, str]:
    config_path = path or Path(os.environ.get(CONFIG_ENVIRONMENT_VARIABLE, default_config_path()))
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError("Global retry mode is not installed. Run install_global.py first.") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Global retry configuration is not valid JSON: {config_path}") from error
    if not isinstance(config, dict):
        raise ValueError(f"Global retry configuration must contain an object: {config_path}")
    real_codex = config.get("real_codex")
    if not isinstance(real_codex, str) or not real_codex:
        raise ValueError(f"Global retry configuration has no real_codex: {config_path}")
    config.setdefault("state_dir", str(config_path.parent / "states"))
    config.setdefault("delays", DEFAULT_DELAYS)
    config.setdefault("client_delays", DEFAULT_CLIENT_DELAYS)
    config.setdefault("language", "en")
    overrides = {
        "delays": os.environ.get("CODEX_RETRY_DELAYS"),
        "client_delays": os.environ.get("CODEX_RETRY_CLIENT_DELAYS"),
        "language": os.environ.get("CODEX_RETRY_LANGUAGE"),
    }
    for key, value in overrides.items():
        if value:
            config[key] = value
    return config


def should_intercept(arguments: List[str], environment: Mapping[str, str]) -> bool:
    if environment.get("CODEX_RETRY_BYPASS", "").lower() in {"1", "true", "yes", "on"}:
        return False
    if "--help" in arguments or "-h" in arguments:
        return False
    return bool(arguments) and arguments[0] == "exec" and (
        len(arguments) == 1 or arguments[1] != "resume"
    )


def ensure_json_output(arguments: List[str]) -> List[str]:
    if "--json" in arguments:
        return list(arguments)
    return ["exec", "--json", *arguments[1:]]


def create_state_file(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{uuid.uuid4().hex}.json"


@contextmanager
def state_lock(state_file: Path) -> Iterator[None]:
    lock_file = state_file.with_suffix(f"{state_file.suffix}.lock")
    try:
        with lock_file.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError as error:
        raise ValueError(f"Retry state is already in use: {state_file}") from error
    try:
        yield
    finally:
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


def run_cli(
    arguments: List[str], cwd: Optional[Path] = None, environment: Optional[Mapping[str, str]] = None
) -> int:
    current_directory = (cwd or Path.cwd()).resolve()
    env = dict(os.environ if environment is None else environment)
    config = load_config()
    real_codex = config["real_codex"]

    if not should_intercept(arguments, env):
        result = subprocess.run([real_codex, *arguments], cwd=str(current_directory), check=False)
        return result.returncode

    state_file = create_state_file(Path(config["state_dir"]))
    command = [real_codex, *ensure_json_output(arguments)]
    retry_arguments = [
        "--command-json",
        json.dumps(command),
        "--cwd",
        str(current_directory),
        "--state-file",
        str(state_file),
        "--delays",
        config["delays"],
        "--client-delays",
        config["client_delays"],
        "--language",
        config["language"],
        "--render-json-output",
    ]
    with state_lock(state_file):
        return codex_retry.main(retry_arguments)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run_cli(list(sys.argv[1:] if argv is None else argv))
    except ValueError as error:
        print(f"Global Codex retry configuration error: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
